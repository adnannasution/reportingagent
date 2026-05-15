"""
app.py — Executive Governance Web App
"""

import os, uuid, tempfile
from datetime import datetime
from flask import Flask, send_from_directory, request, jsonify
from dotenv import load_dotenv
import db, agent, report_generator, sap_parser, control_tower_agent
from analytics_routes import analytics_bp
from custom_chart_routes import custom_chart_bp   

load_dotenv()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB
app.register_blueprint(analytics_bp)  
app.register_blueprint(custom_chart_bp) 

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
        return jsonify({"error": str(e)}), 500

@app.route("/api/reports/<int:report_id>")
def api_report_detail(report_id):
    try:
        row = db.fetch_report_detail(report_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Generate Reports manual ──────────────────────────────────────────────
@app.route("/api/generate/daily", methods=["POST"])
def api_generate_daily():
    try:
        content = report_generator.generate_daily()
        return jsonify({"status": "ok", "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/generate/weekly", methods=["POST"])
def api_generate_weekly():
    try:
        content = report_generator.generate_weekly()
        return jsonify({"status": "ok", "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/generate/monthly", methods=["POST"])
def api_generate_monthly():
    try:
        content = report_generator.generate_monthly()
        return jsonify({"status": "ok", "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Memos ────────────────────────────────────────────────────────────────
@app.route("/api/memos")
def api_memos():
    try:
        rows = db.fetch_memos(limit=100)
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/memos/<int:memo_id>")
def api_memo_detail(memo_id):
    try:
        row = db.fetch_memo_detail(memo_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/memos/generate", methods=["POST"])
def api_generate_memo():
    data = request.json or {}
    report_ids = data.get("report_ids", [])
    title   = data.get("title", f"Memo Eksekutif {datetime.now().strftime('%d %b %Y')}")
    context = data.get("context", "")
    if not report_ids:
        return jsonify({"error": "Pilih minimal 1 report sebagai sumber"}), 400
    try:
        reports = db.fetch_reports_by_ids(report_ids)
        if not reports: return jsonify({"error": "Report tidak ditemukan"}), 404
        content = agent.generate_memo(reports, custom_context=context)
        memo_id = db.save_memo(title, report_ids, content)
        return jsonify({"id": memo_id, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Talking Points ───────────────────────────────────────────────────────
@app.route("/api/talking-points")
def api_talking_points():
    try:
        rows = db.fetch_talking_points(limit=100)
        return jsonify([dict(r) for r in rows])
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/talking-points/<int:tp_id>")
def api_tp_detail(tp_id):
    try:
        row = db.fetch_talking_points_detail(tp_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/talking-points/generate", methods=["POST"])
def api_generate_tp():
    data = request.json or {}
    report_ids = data.get("report_ids", [])
    title   = data.get("title", f"Talking Points {datetime.now().strftime('%d %b %Y')}")
    context = data.get("context", "")
    if not report_ids:
        return jsonify({"error": "Pilih minimal 1 report sebagai sumber"}), 400
    try:
        reports = db.fetch_reports_by_ids(report_ids)
        if not reports: return jsonify({"error": "Report tidak ditemukan"}), 404
        content = agent.generate_talking_points(reports, custom_context=context)
        tp_id   = db.save_talking_points(title, report_ids, content)
        return jsonify({"id": tp_id, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: SAP Upload ───────────────────────────────────────────────────────────
@app.route("/api/sap/summary")
def api_sap_summary():
    try:
        return jsonify(db.get_sap_summary())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/sap/upload", methods=["POST"])
def api_sap_upload():
    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "Tidak ada file yang diupload"}), 400

    batch_id    = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + str(uuid.uuid4())[:6]
    upload_mode = request.form.get("mode", "tambah")  # 'tambah' atau 'replace'
    results     = []

    # Pre-scan semua file untuk tentukan tipe, lalu truncate sekali di awal
    tmp_files = []
    parsed_all = []
    has_notif = False
    has_wo    = False

    for f in files:
        if not f.filename.endswith('.xlsx'):
            results.append({"file": f.filename, "status": "skip", "reason": "Bukan file .xlsx"})
            continue
        tmp = tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False)
        f.save(tmp.name)
        try:
            parsed = sap_parser.parse_file(tmp.name, batch_id)
            parsed_all.append((f.filename, tmp.name, parsed))
            if parsed["type"] == "notification": has_notif = True
            if parsed["type"] == "work_order":   has_wo    = True
        except Exception as e:
            results.append({"file": f.filename, "status": "error", "reason": str(e)})
            os.unlink(tmp.name)

    # Truncate hanya kalau mode replace
    if upload_mode == "replace":
        try:
            if has_notif: db.clear_sap_batch("ALL", "sap_notifications")
            if has_wo:    db.clear_sap_batch("ALL", "sap_work_orders")
        except Exception as e:
            return jsonify({"error": f"Gagal clear data lama: {str(e)}"}), 500

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
            else:
                results.append({"file": filename, "status": "skip",
                                 "reason": "Format tidak dikenali"})
        except Exception as e:
            results.append({"file": filename, "status": "error", "reason": str(e)})
        finally:
            os.unlink(tmppath)

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
        return jsonify({"error": str(e)}), 500

@app.route("/api/control-tower/<int:ct_id>")
def api_ct_detail(ct_id):
    try:
        row = db.fetch_ct_output_detail(ct_id)
        if not row: return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/control-tower/generate", methods=["POST"])
def api_ct_generate():
    data    = request.json or {}
    context = data.get("context", "")
    use_daily = data.get("use_daily_report", True)

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
        return jsonify({"error": str(e)}), 500


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)