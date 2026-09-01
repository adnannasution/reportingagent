"""
app.py — Executive Governance Web App
"""

import os, uuid, tempfile, hashlib
from datetime import datetime, timedelta
from flask import Flask, send_from_directory, request, jsonify, redirect
from dotenv import load_dotenv
import db, agent, report_generator, sap_parser, control_tower_agent
from analytics_routes import analytics_bp
from custom_chart_routes import custom_chart_bp
from auth_routes import auth_bp, PUBLIC_PREFIXES, _current_user, _bootstrap_sso_session, _sso_login_redirect
from rate_limit import limiter

load_dotenv()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
app.config['SECRET_KEY'] = hashlib.sha256(
    ("reportingagent:" + os.getenv("DATABASE_URL", "local")).encode()
).hexdigest()
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

app.register_blueprint(auth_bp)
app.register_blueprint(analytics_bp)
app.register_blueprint(custom_chart_bp)

# ─── RATE LIMITING ──────────────────────────────────────────────────────
# Jaring pengaman terhadap akun disalahgunakan/bug klien yang nge-loop pada
# endpoint yang mahal (generate report/memo/talking points/control tower --
# semuanya panggil LLM -- dan upload & proses file Excel SAP). Endpoint
# baca-saja/ringan sengaja dibiarkan tanpa limit. Pola sama seperti
# ragrel & agent360 pada engagement yang sama (di sana pakai slowapi karena
# FastAPI; di sini Flask-Limiter karena app ini Flask).
limiter.init_app(app)


@app.errorhandler(429)
def ratelimit_handler(e):
    return jsonify({"error": "Terlalu banyak request. Tunggu sebentar lalu coba lagi."}), 429


# ─── CSRF — lapis kedua di atas cookie SameSite=Lax ──────────────────────────
# Session cookie sudah SameSite=Lax, yang sudah memblokir sebagian besar CSRF
# (form/fetch lintas situs tidak ikut kirim cookie untuk request
# POST/PUT/PATCH/DELETE). Ini pertahanan tambahan: browser modern otomatis
# kirim header Sec-Fetch-Site di semua request, menandai asal request lintas
# situs atau bukan -- cek eksplisit ini tidak bergantung sepenuhnya pada
# perilaku SameSite (yang bisa berbeda antar browser/versi). Kalau headernya
# tidak ada (browser sangat lama, atau klien non-browser resmi) tetap
# diloloskan supaya tidak salah blokir -- SameSite tetap jadi jaring pengaman
# utamanya. Pola sama persis dengan ragrel, sso-login, agent360 &
# agentisomasterdata.
_CSRF_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

@app.before_request
def csrf_guard():
    if request.method in _CSRF_UNSAFE_METHODS and request.headers.get("Sec-Fetch-Site") == "cross-site":
        return jsonify({"error": "Request ditolak (indikasi cross-site request forgery)."}), 403


@app.before_request
def require_login():
    path = request.path
    if any(path.startswith(p) for p in PUBLIC_PREFIXES):
        return
    if _current_user() or _bootstrap_sso_session():
        return
    if path.startswith("/api/"):
        return jsonify({"error": "Unauthorized", "redirect": "/login"}), 401
    return redirect(_sso_login_redirect())


# ─── SECURITY HEADERS ──────────────────────────────────────────────────────
# CSP di sini mengizinkan 'unsafe-inline' untuk script/style karena semua
# template pakai <script> inline dan atribut style="..."/onclick="..." secara
# luas -- menghilangkan itu berarti nonce/hash di tiap tag, refactor terpisah
# yang jauh lebih besar dari sekadar "tambah header". Tetap jauh lebih ketat
# daripada tanpa CSP sama sekali: object/frame diblokir, sumber script/style/
# font dibatasi ke domain yang memang dipakai (Google Fonts + Chart.js lewat
# cdnjs). Pola & rasional sama persis dengan ragrel/agent360/agentisomasterdata.
_CSP = (
    "default-src 'self'; "
    "script-src 'self' 'unsafe-inline' https://cdnjs.cloudflare.com; "
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; "
    "img-src 'self' data:; "
    "connect-src 'self'; "
    "object-src 'none'; "
    "base-uri 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "upgrade-insecure-requests"
)

@app.after_request
def security_headers(response):
    response.headers["Content-Security-Policy"] = _CSP
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
    # HSTS hanya kalau request memang datang lewat HTTPS (baca X-Forwarded-Proto
    # dari proxy Railway, jangan andalkan request.scheme yang bisa saja "http"
    # di sisi app walau client-nya sendiri connect via HTTPS).
    proto = request.headers.get("X-Forwarded-Proto", request.scheme)
    if proto == "https":
        response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
    return response


try:
    db.run_migrations()
except Exception as e:
    print(f"[STARTUP] Migrasi gagal: {e}")


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route('/analytics')
def analytics_page():
    return send_from_directory(STATIC_DIR, 'analytics.html')  # pakai STATIC_DIR

@app.route('/custom-chart')                        # route
def custom_chart_page():
    return send_from_directory(STATIC_DIR, 'custom_chart.html')

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ── API: Reports ──────────────────────────────────────────────────────────────
@app.route("/api/reports")
def api_reports():
    rtype = request.args.get("type")
    try:
        rows = db.fetch_reports(report_type=rtype, limit=100)
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[REPORTS LIST ERROR] {e}")
        return jsonify({"error": "Gagal mengambil daftar report"}), 500

@app.route("/api/reports/<int:report_id>")
def api_report_detail(report_id):
    try:
        row = db.fetch_report_detail(report_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        print(f"[REPORT DETAIL ERROR] {e}")
        return jsonify({"error": "Gagal mengambil detail report"}), 500


# ── API: Generate Reports manual ──────────────────────────────────────────────
@app.route("/api/generate/daily", methods=["POST"])
@limiter.limit("10/minute")
def api_generate_daily():
    try:
        content = report_generator.generate_daily()
        return jsonify({"status": "ok", "content": content})
    except Exception as e:
        print(f"[GENERATE DAILY ERROR] {e}")
        return jsonify({"error": "Gagal membuat laporan harian"}), 500

@app.route("/api/generate/weekly", methods=["POST"])
@limiter.limit("10/minute")
def api_generate_weekly():
    try:
        content = report_generator.generate_weekly()
        return jsonify({"status": "ok", "content": content})
    except Exception as e:
        print(f"[GENERATE WEEKLY ERROR] {e}")
        return jsonify({"error": "Gagal membuat laporan mingguan"}), 500

@app.route("/api/generate/monthly", methods=["POST"])
@limiter.limit("10/minute")
def api_generate_monthly():
    try:
        content = report_generator.generate_monthly()
        return jsonify({"status": "ok", "content": content})
    except Exception as e:
        print(f"[GENERATE MONTHLY ERROR] {e}")
        return jsonify({"error": "Gagal membuat laporan bulanan"}), 500


# ── API: Memos ────────────────────────────────────────────────────────────────
@app.route("/api/memos")
def api_memos():
    try:
        rows = db.fetch_memos(limit=100)
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[MEMOS LIST ERROR] {e}")
        return jsonify({"error": "Gagal mengambil daftar memo"}), 500

@app.route("/api/memos/<int:memo_id>")
def api_memo_detail(memo_id):
    try:
        row = db.fetch_memo_detail(memo_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        print(f"[MEMO DETAIL ERROR] {e}")
        return jsonify({"error": "Gagal mengambil detail memo"}), 500

@app.route("/api/memos/generate", methods=["POST"])
@limiter.limit("10/minute")
def api_generate_memo():
    data = request.json or {}
    report_ids = data.get("report_ids", [])
    title   = str(data.get("title", f"Memo Eksekutif {datetime.now().strftime('%d %b %Y')}"))[:255]
    context = str(data.get("context", ""))[:2000]
    if not report_ids:
        return jsonify({"error": "Pilih minimal 1 report sebagai sumber"}), 400
    if not isinstance(report_ids, list) or len(report_ids) > 20:
        return jsonify({"error": "report_ids harus berupa list maksimal 20 item"}), 400
    if not all(isinstance(i, int) for i in report_ids):
        return jsonify({"error": "report_ids harus berisi angka"}), 400
    try:
        reports = db.fetch_reports_by_ids(report_ids)
        if not reports: return jsonify({"error": "Report tidak ditemukan"}), 404
        content = agent.generate_memo(reports, custom_context=context)
        memo_id = db.save_memo(title, report_ids, content)
        return jsonify({"id": memo_id, "content": content})
    except Exception as e:
        print(f"[MEMO GENERATE ERROR] {e}")
        return jsonify({"error": "Gagal membuat memo"}), 500


# ── API: Talking Points ───────────────────────────────────────────────────────
@app.route("/api/talking-points")
def api_talking_points():
    try:
        rows = db.fetch_talking_points(limit=100)
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[TALKING POINTS LIST ERROR] {e}")
        return jsonify({"error": "Gagal mengambil daftar talking points"}), 500

@app.route("/api/talking-points/<int:tp_id>")
def api_tp_detail(tp_id):
    try:
        row = db.fetch_talking_points_detail(tp_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        print(f"[TALKING POINTS DETAIL ERROR] {e}")
        return jsonify({"error": "Gagal mengambil detail talking points"}), 500

@app.route("/api/talking-points/generate", methods=["POST"])
@limiter.limit("10/minute")
def api_generate_tp():
    data = request.json or {}
    report_ids = data.get("report_ids", [])
    title   = str(data.get("title", f"Talking Points {datetime.now().strftime('%d %b %Y')}"))[:255]
    context = str(data.get("context", ""))[:2000]
    if not report_ids:
        return jsonify({"error": "Pilih minimal 1 report sebagai sumber"}), 400
    if not isinstance(report_ids, list) or len(report_ids) > 20:
        return jsonify({"error": "report_ids harus berupa list maksimal 20 item"}), 400
    if not all(isinstance(i, int) for i in report_ids):
        return jsonify({"error": "report_ids harus berisi angka"}), 400
    try:
        reports = db.fetch_reports_by_ids(report_ids)
        if not reports: return jsonify({"error": "Report tidak ditemukan"}), 404
        content = agent.generate_talking_points(reports, custom_context=context)
        tp_id   = db.save_talking_points(title, report_ids, content)
        return jsonify({"id": tp_id, "content": content})
    except Exception as e:
        print(f"[TALKING POINTS GENERATE ERROR] {e}")
        return jsonify({"error": "Gagal membuat talking points"}), 500


# ── API: SAP Upload ───────────────────────────────────────────────────────────
@app.route("/api/sap/summary")
def api_sap_summary():
    try:
        return jsonify(db.get_sap_summary())
    except Exception as e:
        print(f"[SAP SUMMARY ERROR] {e}")
        return jsonify({"error": "Gagal mengambil ringkasan SAP"}), 500

MAX_UPLOAD_FILES = 10

@app.route("/api/sap/upload", methods=["POST"])
@limiter.limit("10/minute")
def api_sap_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Tidak ada file yang diupload"}), 400
    if len(files) > MAX_UPLOAD_FILES:
        return jsonify({"error": f"Maksimal {MAX_UPLOAD_FILES} file per upload"}), 400

    batch_id    = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:6]
    upload_mode = request.form.get("mode", "tambah")  # 'tambah' atau 'replace'
    if upload_mode not in ("tambah", "replace"):
        upload_mode = "tambah"
    # mode=replace TRUNCATE seluruh tabel SAP terkait (notifikasi/WO/BOM/CJI3)
    # -- ini operasi destruktif yang mempengaruhi data bersama semua user,
    # jadi dibatasi khusus admin. mode=tambah (append) tetap terbuka untuk
    # semua user yang sudah login, sama seperti sebelumnya.
    user = _current_user()
    if upload_mode == "replace" and (not user or user.get("role") != "admin"):
        return jsonify({"error": "Hanya admin yang bisa menghapus & mengganti data SAP (mode replace)"}), 403
    results     = []

    # Pre-scan semua file untuk tentukan tipe, lalu truncate sekali di awal
    parsed_all = []
    has_notif = False
    has_wo    = False
    has_bom   = False
    has_cji3  = False

    for f in files:
        safe_name = os.path.basename(f.filename or "")
        if not safe_name.lower().endswith('.xlsx'):
            results.append({"file": safe_name, "status": "skip", "reason": "Bukan file .xlsx"})
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        try:
            f.save(tmp.name)
            tmp.close()
            parsed = sap_parser.parse_file(tmp.name, batch_id)
            parsed_all.append((safe_name, tmp.name, parsed))
            if parsed["type"] == "notification": has_notif = True
            if parsed["type"] == "work_order":   has_wo    = True
            if parsed["type"] == "bom":          has_bom   = True
            if parsed["type"] == "cji3":         has_cji3  = True
        except Exception as e:
            print(f"[SAP UPLOAD PARSE ERROR] file={safe_name} err={e}")
            results.append({"file": safe_name, "status": "error", "reason": "Gagal membaca file"})
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    # Truncate hanya kalau mode replace
    if upload_mode == "replace":
        try:
            if has_notif: db.clear_sap_batch("ALL", "sap_notifications")
            if has_wo:    db.clear_sap_batch("ALL", "sap_work_orders")
            if has_bom:   db.clear_sap_batch("ALL", "sap_bom")
            if has_cji3:  db.clear_sap_batch("ALL", "sap_cji3")
        except Exception as e:
            print(f"[SAP UPLOAD CLEAR ERROR] {e}")
            return jsonify({"error": "Gagal menghapus data lama"}), 500

    # Insert semua
    for filename, tmppath, parsed in parsed_all:
        try:
            if parsed["type"] == "notification":
                db.insert_sap_notifications(parsed["rows"], batch_id)
                results.append({"file": filename, "status": "ok",
                                 "type": "notification", "rows": parsed["count"]})
            elif parsed["type"] == "work_order":
                db.insert_sap_work_orders(parsed["rows"], batch_id)
                results.append({"file": filename, "status": "ok",
                                 "type": "work_order", "rows": parsed["count"]})
            elif parsed["type"] == "bom":
                db.insert_sap_bom(parsed["rows"], batch_id)
                results.append({"file": filename, "status": "ok",
                                 "type": "bom", "rows": parsed["count"]})
            elif parsed["type"] == "cji3":
                db.insert_sap_cji3(parsed["rows"], batch_id)
                results.append({"file": filename, "status": "ok",
                                 "type": "cji3", "rows": parsed["count"]})
            else:
                results.append({"file": filename, "status": "skip",
                                 "reason": "Format tidak dikenali"})
        except Exception as e:
            print(f"[SAP UPLOAD INSERT ERROR] file={filename} err={e}")
            results.append({"file": filename, "status": "error", "reason": "Gagal menyimpan data"})
        finally:
            try:
                os.unlink(tmppath)
            except OSError:
                pass

    total_ok = sum(1 for r in results if r["status"] == "ok")
    return jsonify({"batch_id": batch_id, "results": results,
                    "summary": f"{total_ok}/{len(files)} file berhasil diproses"})


# ── API: Control Tower ────────────────────────────────────────────────────────
@app.route("/api/control-tower")
def api_ct_list():
    try:
        rows = db.fetch_ct_outputs(limit=50)
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        print(f"[CT LIST ERROR] {e}")
        return jsonify({"error": "Gagal mengambil daftar control tower"}), 500

@app.route("/api/control-tower/<int:ct_id>")
def api_ct_detail(ct_id):
    try:
        row = db.fetch_ct_output_detail(ct_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        print(f"[CT DETAIL ERROR] {e}")
        return jsonify({"error": "Gagal mengambil detail control tower"}), 500

@app.route("/api/control-tower/generate", methods=["POST"])
@limiter.limit("10/minute")
def api_ct_generate():
    data    = request.json or {}
    context = str(data.get("context", ""))[:2000]
    use_daily = bool(data.get("use_daily_report", True))

    try:
        sap_data = db.get_sap_data_for_agent()

        # Cek apakah ada data SAP
        total_records = (
            len(sap_data.get("backlog_notifications", [])) +
            len(sap_data.get("stagnant_wo", [])) +
            len(sap_data.get("overdue_wo", []))
        )
        if total_records == 0:
            return jsonify({"error": "Belum ada data SAP. Silakan upload file Excel terlebih dahulu."}), 400

        # Ambil daily report terbaru (opsional)
        daily_content = ""
        if use_daily:
            daily_rows = db.fetch_reports(report_type="daily", limit=1)
            if daily_rows:
                detail = db.fetch_report_detail(daily_rows[0]["id"])
                daily_content = detail["content"] if detail else ""

        content = control_tower_agent.generate_control_tower(
            sap_data, daily_report=daily_content, custom_context=context
        )
        now = datetime.now()
        title = f"Control Tower Report — {now.strftime('%d %b %Y %H:%M')}"
        ct_id = db.save_ct_output("control_tower", title, content)
        return jsonify({"id": ct_id, "content": content})
    except Exception as e:
        print(f"[CT GENERATE ERROR] {e}")
        return jsonify({"error": "Gagal membuat control tower report"}), 500


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)