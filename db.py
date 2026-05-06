"""
db.py — Koneksi PostgreSQL + Auto Migrasi Tabel
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


@contextmanager
def db_cursor():
    conn = get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def run_migrations():
    """Auto migrasi — jalankan saat app start."""
    migrations = [
        # Tabel reports (sudah ada, pastikan tetap ada)
        """
        CREATE TABLE IF NOT EXISTS reports (
            id         SERIAL PRIMARY KEY,
            type       VARCHAR(10) NOT NULL CHECK (type IN ('daily','weekly','monthly')),
            content    TEXT        NOT NULL,
            created_at TIMESTAMP   DEFAULT NOW()
        );
        """,
        # Tabel push_tokens (sudah ada)
        """
        CREATE TABLE IF NOT EXISTS push_tokens (
            id         SERIAL PRIMARY KEY,
            token      TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        # Tabel memos — BARU
        """
        CREATE TABLE IF NOT EXISTS memos (
            id               SERIAL PRIMARY KEY,
            title            VARCHAR(255) NOT NULL,
            source_report_ids INTEGER[]   DEFAULT '{}',
            content          TEXT         NOT NULL,
            created_at       TIMESTAMP    DEFAULT NOW()
        );
        """,
        # Tabel talking_points — BARU
        """
        CREATE TABLE IF NOT EXISTS talking_points (
            id               SERIAL PRIMARY KEY,
            title            VARCHAR(255) NOT NULL,
            source_report_ids INTEGER[]   DEFAULT '{}',
            content          TEXT         NOT NULL,
            created_at       TIMESTAMP    DEFAULT NOW()
        );
        """,
    ]

    conn = get_conn()
    try:
        with conn.cursor() as cur:
            for sql in migrations:
                cur.execute(sql)
        conn.commit()
        print("[DB] ✅ Migrasi selesai.")
    except Exception as e:
        conn.rollback()
        print(f"[DB] ❌ Migrasi gagal: {e}")
        raise
    finally:
        conn.close()


# ── Query helpers ─────────────────────────────────────────────────────────────

def fetch_reports(report_type=None, limit=50):
    with db_cursor() as cur:
        if report_type:
            cur.execute(
                "SELECT id, type, LEFT(content,200) AS preview, created_at "
                "FROM reports WHERE type=%s ORDER BY created_at DESC LIMIT %s",
                (report_type, limit)
            )
        else:
            cur.execute(
                "SELECT id, type, LEFT(content,200) AS preview, created_at "
                "FROM reports ORDER BY created_at DESC LIMIT %s",
                (limit,)
            )
        return cur.fetchall()


def fetch_report_detail(report_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM reports WHERE id=%s", (report_id,))
        return cur.fetchone()


def fetch_reports_by_ids(ids):
    if not ids:
        return []
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, type, content, created_at FROM reports WHERE id = ANY(%s) ORDER BY created_at DESC",
            (ids,)
        )
        return cur.fetchall()


def save_memo(title, source_ids, content):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO memos (title, source_report_ids, content) VALUES (%s, %s, %s) RETURNING id",
            (title, source_ids, content)
        )
        return cur.fetchone()["id"]


def fetch_memos(limit=50):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, source_report_ids, LEFT(content,200) AS preview, created_at "
            "FROM memos ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return cur.fetchall()


def fetch_memo_detail(memo_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM memos WHERE id=%s", (memo_id,))
        return cur.fetchone()


def save_talking_points(title, source_ids, content):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO talking_points (title, source_report_ids, content) VALUES (%s, %s, %s) RETURNING id",
            (title, source_ids, content)
        )
        return cur.fetchone()["id"]


def fetch_talking_points(limit=50):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, source_report_ids, LEFT(content,200) AS preview, created_at "
            "FROM talking_points ORDER BY created_at DESC LIMIT %s",
            (limit,)
        )
        return cur.fetchall()


def fetch_talking_points_detail(tp_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM talking_points WHERE id=%s", (tp_id,))
        return cur.fetchone()
