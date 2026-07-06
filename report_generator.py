"""
report_generator.py — Manual Generate Daily / Weekly / Monthly Report
Logic diambil dari api_server.py (project chatbot), tanpa scheduler.
DB sama, LLM sama (DINOIKI), tabel reports sama.
"""

import os, json
from datetime import datetime, timezone, timedelta
from openai import OpenAI
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()

DATABASE_URL    = os.getenv("DATABASE_URL", "")
DINOIKI_API_KEY = os.getenv("DINOIKI_API_KEY", "")
WIB             = timezone(timedelta(hours=7))

llm_report = OpenAI(
    api_key=DINOIKI_API_KEY,
    base_url="https://ai.dinoiki.com/v1"
)

# ── DB helpers ────────────────────────────────────────────────────────────────
def get_conn():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode="require")

def q(sql, params=None):
    try:
        with get_conn() as conn:
            with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                cur.execute(sql, params or ())
                return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        print(f"[DB] {e}")
        return []

def execute(sql, params=None):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params or ())
        conn.commit()

def save_report(report_type: str, content: str):
    execute(
        "INSERT INTO reports (type, content) VALUES (%s, %s)",
        (report_type, content)
    )

def ask_llm(prompt: str, max_tokens: int = 2000) -> str:
    resp = llm_report.chat.completions.create(
        model="gpt-4o",
        temperature=0.5,
        max_tokens=max_tokens,
        messages=[{"role": "user", "content": prompt}]
    )
    return resp.choices[0].message.content


# ── DAILY ─────────────────────────────────────────────────────────────────────
def gather_daily_data():
    data = {}
    data["bad_actor"] = q("""
        SELECT ru, equipment, status, problem, action_plan, progress, target_date, periode
        FROM bad_actor_monitoring
        WHERE periode = (SELECT MAX(periode) FROM bad_actor_monitoring)
          AND LOWER(COALESCE(status,'')) NOT IN ('closed','complete','selesai','done')
        ORDER BY ru, equipment LIMIT 20
    """)
    data["icu"] = q("""
        SELECT ru, equipment, icu_status, issue, mitigation, progress, target_closed, periode
        FROM icu_monitoring
        WHERE periode = (SELECT MAX(periode) FROM icu_monitoring)
          AND LOWER(COALESCE(icu_status,'')) NOT IN ('closed','resolved','selesai')
        ORDER BY ru, equipment LIMIT 20
    """)
    data["zero_clamp"] = q("""
        SELECT ru, area, unit, equipment, type_damage, tanggal_dipasang, status
        FROM zero_clamp
        WHERE tanggal_dilepas IS NULL OR TRIM(COALESCE(tanggal_dilepas,'')) = ''
        ORDER BY tanggal_dipasang ASC NULLS LAST LIMIT 15
    """)
    data["paf"] = q("""
        SELECT ru, equipment, type, target_realisasi, value, color, periode
        FROM paf
        WHERE periode = (SELECT MAX(periode) FROM paf)
          AND LOWER(COALESCE(color,'')) IN ('red','yellow','orange','merah','kuning')
        ORDER BY ru, equipment LIMIT 20
    """)
    data["power_utility"] = q("""
        SELECT refinery_unit, type_equipment, equipment, status_operation, remark, periode
        FROM power_stream
        WHERE periode = (SELECT MAX(periode) FROM power_stream)
          AND LOWER(COALESCE(status_operation,'')) NOT IN ('normal','standby','ok','siaga')
        ORDER BY refinery_unit LIMIT 15
    """)
    data["critical_utl"] = q("""
        SELECT refinery_unit, equipment, highlight_issue, corrective_action, target_corrective, periode
        FROM critical_eqp_utl
        WHERE periode = (SELECT MAX(periode) FROM critical_eqp_utl)
          AND TRIM(COALESCE(highlight_issue,'')) != ''
        ORDER BY refinery_unit LIMIT 10
    """)
    data["monitoring_operasi"] = q("""
        SELECT refinery_unit, unit_proses, actual, target_sts, limitasi_alert_process, periode
        FROM monitoring_operasi
        WHERE periode = (SELECT MAX(periode) FROM monitoring_operasi)
          AND (TRIM(COALESCE(limitasi_alert_process,'')) != ''
            OR (actual IS NOT NULL AND target_sts IS NOT NULL AND actual < target_sts))
        ORDER BY refinery_unit LIMIT 15
    """)
    return data


def generate_daily() -> str:
    now_wib  = datetime.now(WIB)
    data     = gather_daily_data()
    data_str = json.dumps(data, ensure_ascii=False, default=str, indent=2)
    tgl      = now_wib.strftime("%A, %d %B %Y")
    jam      = now_wib.strftime("%H.%M")
    prompt = f"""Kamu adalah sistem pelaporan otomatis Daily Executive Brief untuk kilang minyak.
Tanggal: {tgl} | {jam} WIB
DATA: {data_str}
Buat Daily Executive Brief dalam Bahasa Indonesia profesional. Sebutkan tag number spesifik. Maksimal 3500 karakter.
FORMAT:
📌 DAILY EXECUTIVE BRIEF
🗓️ {tgl} | ⏰ {jam} WIB
🏭 RINGKASAN EKSEKUTIF
[2-3 kalimat kondisi umum]
━━━━━━━━━━
🔴 PRIORITAS HARI INI
[3-5 isu kritis dengan tag number]
━━━━━━━━━━
📍 STATUS RELIABILITY & OPERASI
• Operasi: [status] • Reliability: [status] • PAF: [status] • Power/Utility: [status] • ICU/Zero Clamp: [status]
━━━━━━━━━━
⚙️ BAD ACTOR WATCHLIST
[Top 5: Tag | RU | Status | Progress]
━━━━━━━━━━
🎯 TINDAK LANJUT HARI INI
[4-5 action item spesifik]
Legend: 🟢 Terkendali | 🟡 Watch | 🟠 Action | 🔴 Urgent
_Generated manual · {tgl}_"""
    report = ask_llm(prompt, max_tokens=2000)
    save_report("daily", report)
    return report


# ── WEEKLY ────────────────────────────────────────────────────────────────────
def gather_weekly_data():
    data = {}
    data["bad_actor_current"] = q("""
        SELECT ru, equipment, status, problem, action_plan, progress, target_date, periode
        FROM bad_actor_monitoring
        WHERE periode = (SELECT MAX(periode) FROM bad_actor_monitoring)
          AND LOWER(COALESCE(status,'')) NOT IN ('closed','complete','selesai','done')
        ORDER BY ru, equipment LIMIT 30
    """)
    data["bad_actor_prev"] = q("""
        SELECT equipment, status, progress FROM bad_actor_monitoring
        WHERE periode = (SELECT MAX(periode) FROM bad_actor_monitoring
                         WHERE periode < (SELECT MAX(periode) FROM bad_actor_monitoring))
        ORDER BY equipment LIMIT 30
    """)
    data["icu_current"] = q("""
        SELECT ru, equipment, icu_status, issue, progress, target_closed, periode
        FROM icu_monitoring
        WHERE periode = (SELECT MAX(periode) FROM icu_monitoring)
          AND LOWER(COALESCE(icu_status,'')) NOT IN ('closed','resolved','selesai')
        ORDER BY ru, equipment LIMIT 25
    """)
    data["paf_current"] = q("""
        SELECT ru, equipment, type, value, color, periode FROM paf
        WHERE periode = (SELECT MAX(periode) FROM paf)
          AND LOWER(COALESCE(color,'')) IN ('red','yellow','orange','merah','kuning')
        ORDER BY ru, equipment LIMIT 25
    """)
    data["paf_prev"] = q("""
        SELECT ru, equipment, type, value, color, periode FROM paf
        WHERE periode = (SELECT MAX(periode) FROM paf
                         WHERE periode < (SELECT MAX(periode) FROM paf))
        ORDER BY ru, equipment LIMIT 25
    """)
    data["power_utility"] = q("""
        SELECT refinery_unit, type_equipment, equipment, status_operation, remark, periode
        FROM power_stream
        WHERE periode = (SELECT MAX(periode) FROM power_stream)
          AND LOWER(COALESCE(status_operation,'')) NOT IN ('normal','standby','ok','siaga')
        ORDER BY refinery_unit LIMIT 20
    """)
    data["readiness_jetty"] = q("""
        SELECT refinery_unit, equipment, status_operation, status_tuks, status_ijin_ops, periode
        FROM readiness_jetty
        WHERE periode = (SELECT MAX(periode) FROM readiness_jetty)
          AND (LOWER(COALESCE(status_operation,'')) NOT IN ('normal','siap','ok','ready')
            OR LOWER(COALESCE(status_tuks,'')) NOT IN ('valid','ok','aktif'))
        ORDER BY refinery_unit, equipment LIMIT 15
    """)
    data["readiness_tank"] = q("""
        SELECT refinery_unit, equipment, status_operational, status_coi, status_atg, periode
        FROM readiness_tank
        WHERE periode = (SELECT MAX(periode) FROM readiness_tank)
          AND LOWER(COALESCE(status_operational,'')) NOT IN ('normal','ok','siap')
        ORDER BY refinery_unit, equipment LIMIT 15
    """)
    data["readiness_spm"] = q("""
        SELECT refinery_unit, equipment, status_operation, status_laik_operasi, periode
        FROM readiness_spm
        WHERE periode = (SELECT MAX(periode) FROM readiness_spm)
          AND LOWER(COALESCE(status_operation,'')) NOT IN ('normal','siap','ok','ready')
        ORDER BY refinery_unit, equipment LIMIT 15
    """)
    data["atg"] = q("""
        SELECT refinery_unit, equipment, status_atg, status_interkoneksi_atg, periode
        FROM atg_monitoring
        WHERE periode = (SELECT MAX(periode) FROM atg_monitoring)
          AND (LOWER(COALESCE(status_atg,'')) NOT IN ('ok','normal','aktif')
            OR LOWER(COALESCE(status_interkoneksi_atg,'')) NOT IN ('aktif','active','ok'))
        ORDER BY refinery_unit LIMIT 20
    """)
    return data


def generate_weekly() -> str:
    now_wib   = datetime.now(WIB)
    data      = gather_weekly_data()
    curr_tags = {r["equipment"] for r in data.get("bad_actor_current", [])}
    prev_tags = {r["equipment"] for r in data.get("bad_actor_prev", [])}
    trend     = {"recurring": sorted(curr_tags & prev_tags), "new": sorted(curr_tags - prev_tags)}
    data_str  = json.dumps(data, ensure_ascii=False, default=str, indent=2)
    tgl       = now_wib.strftime("%A, %d %B %Y | %H.%M")
    prompt = f"""Kamu adalah sistem pelaporan Weekly Executive Review untuk kilang minyak.
Laporan dibuat: {tgl} WIB
TREND BAD ACTOR: {json.dumps(trend, ensure_ascii=False)}
DATA: {data_str}
Buat Weekly Executive Review dalam Bahasa Indonesia formal. Sebutkan tag number spesifik. Maksimal 4000 karakter.
FORMAT:
📘 WEEKLY EXECUTIVE REVIEW
🗓️ Periode: [dari data] | ⏰ {tgl} WIB
🏭 Ringkasan Eksekutif Mingguan [3 kalimat kondisi umum]
━━━━━━━━━━
🔴 1. ISU PRIORITAS MINGGU INI [3-4 isu dengan tag number]
━━━━━━━━━━
⚙️ 2. WEEKLY BAD ACTOR REVIEW [Top 5: TAG | RU | status | trend]
━━━━━━━━━━
🚢 3. WEEKLY READINESS REVIEW • Jetty: [status] • Tank: [status] • SPM: [status] • ATG: [status]
━━━━━━━━━━
🎯 4. TINDAK LANJUT MINGGU DEPAN [4 action item spesifik]
Legend: 🟢 Terkendali | 🟡 Watch | 🟠 Action | 🔴 Urgent
_Generated manual · {tgl}_"""
    report = ask_llm(prompt, max_tokens=2500)
    save_report("weekly", report)
    return report
 

# ── MONTHLY ───────────────────────────────────────────────────────────────────
def gather_monthly_data():
    data = {}
    data["bad_actor_current"] = q("""
        SELECT ru, equipment, status, problem, action_plan, progress, target_date, periode
        FROM bad_actor_monitoring
        WHERE periode = (SELECT MAX(periode) FROM bad_actor_monitoring)
          AND LOWER(COALESCE(status,'')) NOT IN ('closed','complete','selesai','done')
        ORDER BY ru, equipment LIMIT 30
    """)
    data["bad_actor_prev"] = q("""
        SELECT equipment, status, progress FROM bad_actor_monitoring
        WHERE periode = (SELECT MAX(periode) FROM bad_actor_monitoring
                         WHERE periode < (SELECT MAX(periode) FROM bad_actor_monitoring))
        ORDER BY equipment LIMIT 30
    """)
    data["icu_current"] = q("""
        SELECT ru, equipment, icu_status, issue, progress, periode FROM icu_monitoring
        WHERE periode = (SELECT MAX(periode) FROM icu_monitoring)
          AND LOWER(COALESCE(icu_status,'')) NOT IN ('closed','resolved','selesai')
        ORDER BY ru, equipment LIMIT 25
    """)
    data["paf_current"] = q("""
        SELECT ru, equipment, type, value, color, periode FROM paf
        WHERE periode = (SELECT MAX(periode) FROM paf)
          AND LOWER(COALESCE(color,'')) IN ('red','yellow','orange','merah','kuning')
        ORDER BY ru, equipment LIMIT 25
    """)
    data["paf_prev"] = q("""
        SELECT ru, equipment, type, value, color, periode FROM paf
        WHERE periode = (SELECT MAX(periode) FROM paf
                         WHERE periode < (SELECT MAX(periode) FROM paf))
        ORDER BY ru, equipment LIMIT 25
    """)
    data["readiness_jetty"] = q("""
        SELECT refinery_unit, equipment, status_operation, status_tuks, periode
        FROM readiness_jetty
        WHERE periode = (SELECT MAX(periode) FROM readiness_jetty)
          AND LOWER(COALESCE(status_operation,'')) NOT IN ('normal','siap','ok','ready')
        ORDER BY refinery_unit, equipment LIMIT 15
    """)
    data["readiness_tank"] = q("""
        SELECT refinery_unit, equipment, status_operational, status_coi, periode
        FROM readiness_tank
        WHERE periode = (SELECT MAX(periode) FROM readiness_tank)
          AND LOWER(COALESCE(status_operational,'')) NOT IN ('normal','ok','siap')
        ORDER BY refinery_unit, equipment LIMIT 15
    """)
    data["readiness_spm"] = q("""
        SELECT refinery_unit, equipment, status_operation, status_laik_operasi, periode
        FROM readiness_spm
        WHERE periode = (SELECT MAX(periode) FROM readiness_spm)
          AND LOWER(COALESCE(status_operation,'')) NOT IN ('normal','siap','ok','ready')
        ORDER BY refinery_unit, equipment LIMIT 15
    """)
    data["atg"] = q("""
        SELECT refinery_unit, equipment, status_atg, status_interkoneksi_atg, periode
        FROM atg_monitoring
        WHERE periode = (SELECT MAX(periode) FROM atg_monitoring)
          AND (LOWER(COALESCE(status_atg,'')) NOT IN ('ok','normal','aktif')
            OR LOWER(COALESCE(status_interkoneksi_atg,'')) NOT IN ('aktif','active','ok'))
        ORDER BY refinery_unit LIMIT 20
    """)
    return data


def generate_monthly() -> str:
    now_wib  = datetime.now(WIB)
    data     = gather_monthly_data()
    data_str = json.dumps(data, ensure_ascii=False, default=str, indent=2)
    tgl      = now_wib.strftime("%A, %d %B %Y | %H.%M")
    prompt = f"""Kamu adalah sistem pelaporan Monthly Management Review untuk kilang minyak.
Laporan dibuat: {tgl} WIB
DATA: {data_str}
Buat Monthly Management Review dalam Bahasa Indonesia formal. Sebutkan tag number spesifik. Maksimal 5000 karakter.
FORMAT:
📙 MONTHLY MANAGEMENT REVIEW
🗓️ Periode: [dari data] | ⏰ Disusun: {tgl} WIB
🏭 Ringkasan Eksekutif Bulanan [3-4 kalimat kondisi umum]
━━━━━━━━━━
🔴 1. MANAGEMENT HEADLINE BULAN INI [3 headline utama]
━━━━━━━━━━
📍 2. MONTHLY PERFORMANCE SUMMARY
• Operasi: [status] • Reliability: [status] • PAF: [status] • Readiness: [status]
━━━━━━━━━━
🔥 3. TOP BAD ACTOR BULAN INI [Top 5: TAG | RU | status | trend]
━━━━━━━━━━
🚢 4. MONTHLY READINESS REVIEW
• Jetty: [status] • Tank: [status] • SPM: [status] • ATG: [status]
━━━━━━━━━━
🎯 5. MANAGEMENT FOCUS BULAN DEPAN [4 action item spesifik]
Legend: 🟢 Terkendali | 🟡 Watch | 🟠 Action | 🔴 Urgent
_Generated manual · {tgl}_"""
    report = ask_llm(prompt, max_tokens=3000)
    save_report("monthly", report)
    return report