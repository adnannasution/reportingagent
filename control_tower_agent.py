"""
control_tower_agent.py — Operations & Maintenance Control Tower Agent
Memantau eksekusi maintenance harian: backlog, overdue, stagnant WO, bottleneck.
"""

import os, json
from datetime import datetime, timezone, timedelta
from openai import OpenAI

DINOIKI_API_KEY = os.getenv("DINOIKI_API_KEY", "")
WIB = timezone(timedelta(hours=7))

llm = OpenAI(api_key=DINOIKI_API_KEY, base_url="https://ai.dinoiki.com/v1")

SYSTEM_PROMPT = """Anda adalah Operations & Maintenance Control Tower Agent untuk kilang minyak.

Tugas Anda adalah memantau operasi harian dan eksekusi maintenance untuk mendeteksi isu yang dapat mengganggu reliability, availability, dan kelancaran proses bisnis maintenance.

FOKUS ANALISIS:
- Notifikasi outstanding (OSNO) yang belum diproses menjadi WO — terutama criticality H/I
- Work Order stagnant: sudah REL tapi tidak ada kemajuan eksekusi
- WO overdue: basic finish date sudah lewat, belum TECO/CLSD
- WO belum release (CRTD): ada bottleneck di tahap planning/approval
- Equipment berulang: notif atau WO berulang pada aset yang sama
- Closure administratif: TECO tanpa actual finish yang jelas

ATURAN:
- Prioritaskan isu yang berdampak pada continuity of operation
- Bedakan: issue operasional, issue maintenance execution, issue administrasi data
- Jangan simpulkan root cause tanpa evidence dari data
- Tandai repeated notification dan repeated work pada asset yang sama
- Criticality: H/I = High/Immediate (prioritas utama), M = Medium, L = Low

GUARDRAIL:
- Backlog tinggi tidak selalu buruk — perhatikan criticality-nya
- Jangan nilai "selesai teknis" bila hanya status administratif tanpa actual finish
- Tandai bila data tidak konsisten (contoh: TECO tanpa actual finish)

FORMAT OUTPUT WAJIB (gunakan heading ## ini persis):
## 1. Kondisi Operasi & Maintenance Hari Ini
(ringkasan 2-3 kalimat kondisi umum dari data yang tersedia)

## 2. Top Execution Concerns
(maksimal 5 isu paling kritis, urutkan dari paling berdampak, sebutkan nomor WO/notif dan equipment spesifik)

## 3. Backlog / Overdue Watchlist
(daftar notif OSNO belum WO + WO overdue yang perlu perhatian, fokus criticality H/I/M)

## 4. Bottleneck Process
(identifikasi di mana aliran WO tersumbat: CRTD belum REL, REL belum jalan, atau notif tidak di-WO-kan)

## 5. Risiko ke Reliability / Availability
(dampak potensial ke operasi jika isu tidak diselesaikan)

## 6. Required Follow-up
(tindakan konkret yang diperlukan + PIC/WorkCenter yang bertanggung jawab)"""


def generate_control_tower(sap_data: dict, daily_report: str = "", custom_context: str = "") -> str:
    now_wib = datetime.now(WIB)
    tgl = now_wib.strftime("%A, %d %B %Y | %H.%M WIB")

    data_str = json.dumps(sap_data, ensure_ascii=False, default=str, indent=2)

    user_msg = f"""DATA SAP MAINTENANCE (per {tgl}):

{data_str}
"""
    if daily_report:
        user_msg += f"\nDAILY OPERATION REPORT TERKINI:\n{daily_report[:2000]}\n"

    if custom_context:
        user_msg += f"\nKONTEKS TAMBAHAN:\n{custom_context}\n"

    user_msg += f"""
Analisis data di atas dan buat Control Tower Report lengkap sesuai format yang ditentukan.
Tanggal analisis: {tgl}
Sebutkan nomor WO, nomor notifikasi, dan tag equipment secara spesifik.
Maksimal 4000 karakter."""

    resp = llm.chat.completions.create(
        model="gpt-4o",
        temperature=0.4,
        max_tokens=2500,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": user_msg},
        ]
    )
    return resp.choices[0].message.content