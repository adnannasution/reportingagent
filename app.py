"""
app.py — Executive Governance Web App
"""

import os
from datetime import datetime
from flask import Flask, send_from_directory, request, jsonify
from dotenv import load_dotenv
import db
import agent
import report_generator

load_dotenv()

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
STATIC_DIR = os.path.join(BASE_DIR, "static")

app = Flask(__name__, static_folder=STATIC_DIR)

try:
    db.run_migrations()
except Exception as e:
    print(f"[STARTUP] Migrasi gagal: {e}")


# ── Pages ─────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(STATIC_DIR, "index.html")

@app.route("/health")
def health():
    return jsonify({"status": "ok"})


# ── API: Reports (read) ───────────────────────────────────────────────────────
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
        if not row:
            return jsonify({"error": "Not found"}), 404
        return jsonify(dict(row))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── API: Generate Reports (manual trigger) ────────────────────────────────────
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
        if not row:
            return jsonify({"error": "Not found"}), 404
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
        if not reports:
            return jsonify({"error": "Report tidak ditemukan"}), 404
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
        if not row:
            return jsonify({"error": "Not found"}), 404
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
        if not reports:
            return jsonify({"error": "Report tidak ditemukan"}), 404
        content = agent.generate_talking_points(reports, custom_context=context)
        tp_id   = db.save_talking_points(title, report_ids, content)
        return jsonify({"id": tp_id, "content": content})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Main ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)