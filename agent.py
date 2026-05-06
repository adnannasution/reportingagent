"""
agent.py — Executive Governance & Reporting Agent
Mengubah temuan teknis menjadi narasi manajemen yang ringkas dan tajam.
"""

import os
from langchain_openai import ChatOpenAI

DINOIKI_API_KEY = os.getenv("DINOIKI_API_KEY", "")

llm = ChatOpenAI(
    model="gpt-4o-mini",
    api_key=DINOIKI_API_KEY,
    base_url="https://ai.dinoiki.com/v1",
    temperature=0.3,
)


SYSTEM_PROMPT = """Anda adalah Executive Governance & Reporting Agent untuk operasi kilang minyak.

Tugas Anda adalah mengubah temuan teknis dan operasional menjadi narasi manajemen yang ringkas, tajam, dan siap dipakai oleh Senior Manager, VP, GM, atau Director.

TUJUAN OUTPUT:
- Mudah dibaca dalam 1–3 menit
- Menonjolkan isu paling material
- Menyampaikan implikasi bisnis dan operasional
- Menyebutkan tindakan atau keputusan yang dibutuhkan

ATURAN WAJIB:
- Gunakan bahasa eksekutif (formal, ringkas, tegas)
- Jangan terlalu teknis kecuali diperlukan
- Pisahkan fakta, risiko, dan rekomendasi
- Sertakan caveat bila data belum lengkap
- Utamakan clarity, priority, dan actionability
- Jangan membuat narasi lebih optimistis dari evidence
- Jangan menyembunyikan severity
- Jangan terlalu panjang

FORMAT OUTPUT WAJIB (gunakan heading ini persis):
## 1. Executive Headline
(1-2 kalimat paling kritis hari ini)

## 2. Current Status
(ringkasan status operasional saat ini)

## 3. Top Issues Requiring Attention
(maksimal 5 isu utama, urutkan dari paling kritis)

## 4. Business / Operational Implication
(dampak bisnis, finansial, atau reputasional)

## 5. Required Follow-up
(tindakan konkret yang dibutuhkan + pemilik/PIC)

## 6. Data Caveat
(batasan data, asumsi, atau hal yang belum terverifikasi)"""


MEMO_SYSTEM = SYSTEM_PROMPT + """

OUTPUT TAMBAHAN UNTUK MEMO:
- Format seperti nota dinas / executive memo
- Sertakan: Kepada, Dari, Perihal, Tanggal
- Gunakan bahasa formal Indonesia
- Tutup dengan bagian "Mohon Arahan / Keputusan"
"""

TALKING_POINTS_SYSTEM = SYSTEM_PROMPT + """

OUTPUT UNTUK TALKING POINTS:
- Format bullet points singkat, masing-masing 1-2 kalimat
- Urutan: Opening → Status Kritis → Isu Utama → Keputusan yang Diperlukan → Closing
- Setiap poin harus bisa diucapkan dalam 10-15 detik
- Sertakan catatan "[PAUSE]" di antara bagian untuk jeda pimpinan
- Cocok untuk briefing lisan 5-10 menit
"""


def _combine_reports(reports):
    """Gabungkan konten beberapa report menjadi satu konteks."""
    parts = []
    for r in reports:
        label = f"[{r['type'].upper()} REPORT — {r['created_at'].strftime('%d %b %Y')}]"
        parts.append(f"{label}\n{r['content']}")
    return "\n\n{'='*60}\n\n".join(parts)


def generate_memo(reports, custom_context=""):
    """Generate executive memo dari satu atau beberapa report."""
    combined = _combine_reports(reports)
    user_msg = f"""Berikut adalah data operasional kilang yang perlu diubah menjadi Executive Memo:

{combined}
"""
    if custom_context:
        user_msg += f"\nKonteks tambahan dari user:\n{custom_context}"

    user_msg += "\n\nBuat Executive Memo lengkap sesuai format yang ditentukan."

    response = llm.invoke([
        {"role": "system", "content": MEMO_SYSTEM},
        {"role": "user",   "content": user_msg},
    ])
    return response.content


def generate_talking_points(reports, custom_context=""):
    """Generate talking points untuk briefing pimpinan."""
    combined = _combine_reports(reports)
    user_msg = f"""Berikut adalah data operasional kilang untuk persiapan briefing pimpinan:

{combined}
"""
    if custom_context:
        user_msg += f"\nKonteks tambahan / fokus briefing:\n{custom_context}"

    user_msg += "\n\nBuat Talking Points lengkap sesuai format yang ditentukan."

    response = llm.invoke([
        {"role": "system", "content": TALKING_POINTS_SYSTEM},
        {"role": "user",   "content": user_msg},
    ])
    return response.content