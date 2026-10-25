"""
data_api.py — API data (baca-saja) untuk aplikasi lain: /api/v1/*

Data SAP yang diunggah ke Reporting Agent diekspos untuk disinkron ke aplikasi lain (mis. App-Rel).
Kontraknya sama dengan API data Excellent Dashboard dan agentisomasterdata, supaya klien sinkron
yang sama bisa dipakai:

  GET /api/v1/datasets                       daftar dataset: row_count, version, updated_at
  GET /api/v1/pages                          halaman -> dataset anggotanya
  GET /api/v1/datasets/<nama>                baris data, berhalaman (limit/after), filter, pilih kolom
  GET /api/v1/datasets/<nama>/schema         kolom + tipe
  GET /api/v1/datasets/<nama>/version        version ringan (untuk cek "ada yang berubah?")
  GET /api/v1/datasets/<nama>/export         seluruh dataset sekali jalan (CSV / NDJSON, streaming)

Dataset:
  sap-bom            sap_bom: Bill of Materials SAP per equipment (komponen, material, kuantitas, item text, ...)
  sap-notifications  sap_notifications: notifikasi SAP IW29 (jenis M1/M2/M3, tanggal, equipment, functional
                     location, status, prioritas, malfunction start/end bila ada di layout ekspor, ...)

Auth: header `X-API-Key: <kunci>` (atau `Authorization: Bearer <kunci>`). Kunci diisi di Railway:
  DATA_API_KEYS = nama1=kunci1,nama2=kunci2       (satu kunci per aplikasi pemakai; cabut = hapus dari daftar)
  DATA_API_RATE_PER_MIN (opsional, bawaan 120)    batas permintaan per kunci per menit
Env kosong = API terkunci (503). Kunci TIDAK diterima lewat query string (supaya tidak masuk log).
Endpoint ini tidak memakai login SSO (aplikasi lain memanggil dengan API key).

`version` berubah setiap kali isi tabel ditulis (upload SAP). Aplikasi pemanggil cukup membandingkan
dengan version yang ia simpan: sama = tidak perlu menarik ulang.
"""

import csv
import hmac
import io
import json
import os
import threading
import time
from collections import defaultdict, deque
from datetime import date, datetime
from decimal import Decimal
from functools import wraps
from typing import Optional

import psycopg2.extras
from flask import Blueprint, Response, g, jsonify, request
from psycopg2 import DataError, ProgrammingError

import db

data_api_bp = Blueprint("data_api", __name__, url_prefix="/api/v1")
PUBLIC_PREFIX = "/api/v1/"

# nama dataset -> tabel, label, halaman
_D = [
    ("sap-bom", "sap_bom", "SAP BOM (Bill of Materials)", "sap-upload"),
    ("sap-notifications", "sap_notifications", "SAP Notifikasi (IW29)", "sap-upload"),
]
DATASETS = {n: {"name": n, "table": t, "label": l, "page": p} for n, t, l, p in _D}

DEFAULT_LIMIT, MAX_LIMIT = 1000, 5000
_RESERVED = {"limit", "after", "fields", "format"}
_OPS = {"in", "gte", "lte", "gt", "lt", "like", "ne"}


class ApiError(Exception):
    def __init__(self, status: int, detail: str, headers: Optional[dict] = None):
        super().__init__(detail)
        self.status, self.detail, self.headers = status, detail, headers or {}


@data_api_bp.errorhandler(ApiError)
def _api_error(e: ApiError):
    resp = jsonify({"detail": e.detail})
    resp.status_code = e.status
    for k, v in e.headers.items():
        resp.headers[k] = v
    return resp


def query_df(sql: str, params=None) -> list:
    conn = db.get_conn()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params or [])
            return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()


# ── Auth + batas laju ──────────────────────────────────────────
def _keys() -> dict:
    out = {}
    for part in os.getenv("DATA_API_KEYS", "").split(","):
        if "=" in part:
            name, _, key = part.partition("=")
            if name.strip() and key.strip():
                out[name.strip()] = key.strip()
    return out


_hits: dict = defaultdict(deque)
_exports: dict = defaultdict(int)
_rl_lock = threading.Lock()


def require_key(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        keys = _keys()
        if not keys:
            raise ApiError(503, "API data belum diaktifkan di server (DATA_API_KEYS belum diisi).")
        auth = request.headers.get("Authorization", "")
        supplied = request.headers.get("X-API-Key", "").strip() or (
            auth[7:].strip() if auth.lower().startswith("bearer ") else "")
        name = next((n for n, k in keys.items()
                     if supplied and hmac.compare_digest(supplied.encode(), k.encode())), None)
        if not name:
            raise ApiError(401, "API key tidak valid. Kirim header X-API-Key.")
        limit = int(os.getenv("DATA_API_RATE_PER_MIN", "120") or 120)
        now = time.time()
        with _rl_lock:
            q = _hits[name]
            while q and q[0] < now - 60:
                q.popleft()
            if len(q) >= limit:
                retry = int(60 - (now - q[0])) + 1
                raise ApiError(429, f"Terlalu banyak permintaan (maks {limit}/menit).", {"Retry-After": str(retry)})
            q.append(now)
        g.api_client = name
        return fn(*args, **kwargs)
    return wrapper


# ── Skema + versi ──────────────────────────────────────────────
_schema_cache: dict = {}
_meta_cache: dict = {}


def _ds(name: str) -> dict:
    d = DATASETS.get(name)
    if not d:
        raise ApiError(404, f"Dataset '{name}' tidak ada. Lihat GET /api/v1/datasets.")
    return d


def _schema(name: str) -> dict:
    if name in _schema_cache:
        return _schema_cache[name]
    table = _ds(name)["table"]
    cols = query_df("""
        SELECT column_name AS name, data_type AS type, is_nullable = 'YES' AS nullable
        FROM information_schema.columns WHERE table_schema = 'public' AND table_name = %s ORDER BY ordinal_position
    """, [table])
    if not cols:
        raise ApiError(404, f"Tabel dataset '{name}' belum tersedia.")
    names = [c["name"] for c in cols]
    info = {"columns": cols, "names": set(names), "order": "id" if "id" in names else names[0]}
    _schema_cache[name] = info
    return info


def _meta(name: str, fresh: bool = False) -> dict:
    hit = _meta_cache.get(name)
    if hit and not fresh and time.time() - hit[0] < 15:
        return hit[1]
    d = _ds(name)
    _schema(name)
    table = d["table"]
    cnt = query_df(f'SELECT COUNT(*) AS n FROM "{table}"')[0]["n"]
    st = query_df("SELECT n_tup_ins, n_tup_upd, n_tup_del FROM pg_stat_user_tables WHERE relname = %s", [table])
    s = st[0] if st else {"n_tup_ins": 0, "n_tup_upd": 0, "n_tup_del": 0}
    version = f"{cnt}-{s['n_tup_ins']}-{s['n_tup_upd']}-{s['n_tup_del']}"
    updated = None
    if "uploaded_at" in _schema(name)["names"]:
        t = query_df(f'SELECT MAX(uploaded_at) AS t FROM "{table}"')[0]["t"]
        updated = t.isoformat() if t else None
    meta = {"row_count": cnt, "version": version, "updated_at": updated}
    _meta_cache[name] = (time.time(), meta)
    return meta


# ── Pembentuk query (filter / kolom / urutan) ──────────────────
def _qi(col: str) -> str:
    return '"' + col.replace('"', '""') + '"'


def _where(name: str, params: dict, after: Optional[str]) -> tuple:
    sc = _schema(name)
    clauses, args = [], []
    for key, val in params.items():
        if key in _RESERVED:
            continue
        col, _, op = key.partition("__")
        if col not in sc["names"]:
            raise ApiError(400, f"Kolom '{col}' tidak ada di dataset '{name}'. Lihat /schema.")
        if op and op not in _OPS:
            raise ApiError(400, f"Operator '__{op}' tidak dikenal. Boleh: {', '.join(sorted(_OPS))}.")
        c = _qi(col)
        if op == "in":
            vals = tuple(v for v in val.split(",") if v != "")
            if not vals:
                continue
            clauses.append(f"{c} IN %s"); args.append(vals)
        elif op == "like":
            clauses.append(f"{c}::text ILIKE %s"); args.append(f"%{val}%")
        elif op in ("gte", "lte", "gt", "lt", "ne"):
            sym = {"gte": ">=", "lte": "<=", "gt": ">", "lt": "<", "ne": "<>"}[op]
            clauses.append(f"{c} {sym} %s"); args.append(val)
        elif val.lower() in ("null", "__null__"):
            clauses.append(f"{c} IS NULL")
        else:
            clauses.append(f"{c} = %s"); args.append(val)
    if after not in (None, ""):
        clauses.append(f"{_qi(sc['order'])} > %s"); args.append(after)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def _select(name: str, fields: Optional[str]) -> str:
    sc = _schema(name)
    if not fields:
        return "*"
    cols = [f.strip() for f in fields.split(",") if f.strip()]
    bad = [c for c in cols if c not in sc["names"]]
    if bad:
        raise ApiError(400, f"Kolom tidak ada: {', '.join(bad)}. Lihat /schema.")
    return ", ".join(_qi(c) for c in cols)


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    if isinstance(o, (datetime, date)):
        return o.isoformat()
    return str(o)


def _clean(row: dict) -> dict:
    return {k: _json_default(v) if isinstance(v, (Decimal, datetime, date)) else v for k, v in row.items()}


def _db_error(e: Exception):
    raise ApiError(400, f"Filter tidak valid untuk tipe kolom: {str(e).splitlines()[0][:160]}")


# ── Endpoint ───────────────────────────────────────────────────
@data_api_bp.get("/datasets")
@require_key
def list_datasets():
    out = []
    for name, d in DATASETS.items():
        try:
            m = _meta(name)
        except ApiError:
            continue
        out.append({"name": name, "label": d["label"], "page": d["page"], **m})
    return jsonify({"count": len(out), "datasets": out})


@data_api_bp.get("/pages")
@require_key
def list_pages():
    pages: dict = {}
    for name, d in DATASETS.items():
        pages.setdefault(d["page"], []).append(name)
    return jsonify({"pages": [{"page": p, "datasets": ds} for p, ds in pages.items()]})


@data_api_bp.get("/datasets/<name>/schema")
@require_key
def dataset_schema(name):
    d, sc = _ds(name), _schema(name)
    return jsonify({"name": name, "label": d["label"], "page": d["page"], "order_by": sc["order"],
                    "columns": sc["columns"]})


@data_api_bp.get("/datasets/<name>/version")
@require_key
def dataset_version(name):
    _ds(name)
    return jsonify({"name": name, **_meta(name, fresh=True)})


@data_api_bp.get("/datasets/<name>")
@require_key
def dataset_rows(name):
    sc = _schema(name)
    try:
        limit = int(request.args.get("limit", DEFAULT_LIMIT))
    except ValueError:
        raise ApiError(400, "limit harus angka.")
    if not 1 <= limit <= MAX_LIMIT:
        raise ApiError(400, f"limit harus 1..{MAX_LIMIT}.")
    fields = request.args.get("fields")
    after = request.args.get("after")
    sel = _select(name, fields)
    where, args = _where(name, request.args.to_dict(), after)
    order = _qi(sc["order"])
    need_cursor = bool(fields) and sc["order"] not in [f.strip() for f in fields.split(",")]
    sql = (f'SELECT {sel}{", " + order + " AS __cursor" if need_cursor else ""} '
           f'FROM "{_ds(name)["table"]}"{where} ORDER BY {order} LIMIT %s')
    try:
        rows = query_df(sql, args + [limit + 1])
    except (DataError, ProgrammingError) as e:
        _db_error(e)
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = str(last.get("__cursor", last.get(sc["order"])))
    for r in rows:
        r.pop("__cursor", None)
    meta = _meta(name)
    return jsonify({"dataset": name, "version": meta["version"], "updated_at": meta["updated_at"],
                    "returned": len(rows), "next_cursor": next_cursor, "rows": [_clean(r) for r in rows]})


@data_api_bp.get("/datasets/<name>/export")
@require_key
def dataset_export(name):
    d = _ds(name)
    sc = _schema(name)
    fmt = request.args.get("format", "csv")
    if fmt not in ("csv", "ndjson"):
        raise ApiError(400, "format harus csv atau ndjson.")
    sel = _select(name, request.args.get("fields"))
    where, args = _where(name, request.args.to_dict(), None)
    sql = f'SELECT {sel} FROM "{d["table"]}"{where} ORDER BY {_qi(sc["order"])}'
    client = g.api_client
    with _rl_lock:
        if _exports[client] >= 2:
            raise ApiError(429, "Maksimal 2 ekspor berjalan bersamaan per kunci.", {"Retry-After": "30"})
        _exports[client] += 1
    try:
        meta = _meta(name, fresh=True)
    except Exception:
        with _rl_lock:
            _exports[client] = max(0, _exports[client] - 1)
        raise

    def gen():
        conn = db.get_conn()
        try:
            cur = conn.cursor(name=f"exp_{int(time.time() * 1000)}")   # server-side cursor: hemat memori
            cur.itersize = 5000
            try:
                cur.execute(sql, args)
            except (DataError, ProgrammingError) as e:
                yield json.dumps({"error": str(e).splitlines()[0][:160]}) + "\n"
                return
            header_done = False
            buf = io.StringIO()
            w = csv.writer(buf)
            while True:
                batch = cur.fetchmany(5000)
                if not batch:
                    break
                cols = [c[0] for c in cur.description]
                if fmt == "csv":
                    if not header_done:
                        w.writerow(cols); header_done = True
                    for row in batch:
                        w.writerow(["" if v is None else (_json_default(v) if isinstance(v, (Decimal, datetime, date)) else v)
                                    for v in row])
                    yield buf.getvalue(); buf.seek(0); buf.truncate(0)
                else:
                    yield "".join(json.dumps(dict(zip(cols, row)), default=_json_default, ensure_ascii=False) + "\n"
                                  for row in batch)
            if fmt == "csv" and not header_done:
                w.writerow([c[0] for c in cur.description or []]); yield buf.getvalue()
        finally:
            conn.close()
            with _rl_lock:
                _exports[client] = max(0, _exports[client] - 1)

    mt = "text/csv; charset=utf-8" if fmt == "csv" else "application/x-ndjson"
    headers = {"X-Dataset-Version": meta["version"], "X-Dataset-Rows": str(meta["row_count"]),
               "Content-Disposition": f'attachment; filename="{name}.{fmt}"'}
    return Response(gen(), mimetype=mt, headers=headers)
