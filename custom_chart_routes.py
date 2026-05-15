"""
custom_chart_routes.py — Custom Chart Builder API
Endpoints:
  GET  /api/custom/config        → kolom & aggregasi tersedia per tabel
  POST /api/custom/chart         → build chart dari konfigurasi user
  GET  /api/custom/filter-values → nilai unik suatu kolom untuk dropdown filter
"""

import traceback
from flask import Blueprint, request, jsonify
from db import db_cursor

custom_chart_bp = Blueprint("custom_chart", __name__)

# ─────────────────────────────────────────────────────────────────────────────
#  Definisi kolom & aggregasi (whitelist — keamanan SQL injection)
# ─────────────────────────────────────────────────────────────────────────────
CONFIG = {
    "notifications": {
        "label": "SAP Notifikasi (IW29)",
        "table": "sap_notifications",
        "x_cols": [
            {"key": "notif_type",    "label": "Tipe Notifikasi"},
            {"key": "system_status", "label": "Status Notifikasi"},
            {"key": "criticality",   "label": "Kritikalitas"},
            {"key": "location",      "label": "Lokasi / Area"},
            {"key": "main_workctr",  "label": "Workcenter"},
            {"key": "planner_group", "label": "Planner Group"},
        ],
        "aggregations": [
            {"key": "count",            "label": "Jumlah Notifikasi",          "sql": "COUNT(*)"},
            {"key": "count_with_wo",    "label": "Notif ada WO",               "sql": "SUM(CASE WHEN order_no IS NOT NULL AND order_no != '' THEN 1 ELSE 0 END)"},
            {"key": "count_no_wo",      "label": "Notif tanpa WO (backlog)",   "sql": "SUM(CASE WHEN order_no IS NULL OR order_no = '' THEN 1 ELSE 0 END)"},
            {"key": "count_overdue",    "label": "Notif Overdue",              "sql": "SUM(CASE WHEN required_end < CURRENT_DATE THEN 1 ELSE 0 END)"},
            {"key": "pct_with_wo",      "label": "% Konversi ke WO",          "sql": "ROUND(100.0 * SUM(CASE WHEN order_no IS NOT NULL AND order_no != '' THEN 1 ELSE 0 END) / NULLIF(COUNT(*), 0), 1)"},
        ],
        "filter_cols": [
            {"key": "notif_type",    "label": "Tipe Notifikasi"},
            {"key": "system_status", "label": "Status"},
            {"key": "criticality",   "label": "Kritikalitas"},
            {"key": "location",      "label": "Lokasi"},
            {"key": "main_workctr",  "label": "Workcenter"},
            {"key": "planner_group", "label": "Planner Group"},
        ],
    },
    "work_orders": {
        "label": "SAP Work Order (IW39)",
        "table": "sap_work_orders",
        "x_cols": [
            {"key": "order_type",    "label": "Order Type"},
            {"key": "system_status", "label": "Status WO"},
            {"key": "criticality",   "label": "Kritikalitas"},
            {"key": "location",      "label": "Lokasi / Area"},
            {"key": "main_workctr",  "label": "Workcenter"},
            {"key": "plant",         "label": "Plant"},
            {"key": "priority",      "label": "Prioritas"},
            {"key": "planner_group", "label": "Planner Group"},
        ],
        "aggregations": [
            {"key": "count",          "label": "Jumlah WO",                "sql": "COUNT(*)"},
            {"key": "sum_plan",       "label": "Total Plan Cost",           "sql": "ROUND(SUM(total_plan_cost)::NUMERIC, 0)"},
            {"key": "sum_actual",     "label": "Total Actual Cost",         "sql": "ROUND(SUM(total_act_cost)::NUMERIC, 0)"},
            {"key": "avg_plan",       "label": "Rata-rata Plan Cost",       "sql": "ROUND(AVG(total_plan_cost)::NUMERIC, 0)"},
            {"key": "avg_actual",     "label": "Rata-rata Actual Cost",     "sql": "ROUND(AVG(total_act_cost)::NUMERIC, 0)"},
            {"key": "cost_overrun",   "label": "Total Cost Overrun (Δ)",    "sql": "ROUND(SUM(total_act_cost - total_plan_cost)::NUMERIC, 0)"},
            {"key": "count_overdue",  "label": "WO Overdue",                "sql": "SUM(CASE WHEN basic_fin_date < CURRENT_DATE AND system_status NOT ILIKE '%%TECO%%' AND system_status NOT ILIKE '%%CLSD%%' THEN 1 ELSE 0 END)"},
        ],
        "filter_cols": [
            {"key": "order_type",    "label": "Order Type"},
            {"key": "system_status", "label": "Status WO"},
            {"key": "criticality",   "label": "Kritikalitas"},
            {"key": "location",      "label": "Lokasi"},
            {"key": "main_workctr",  "label": "Workcenter"},
            {"key": "plant",         "label": "Plant"},
            {"key": "priority",      "label": "Prioritas"},
        ],
    },
}

# Whitelist untuk validasi
def _allowed_x(table_key):
    return {c["key"] for c in CONFIG[table_key]["x_cols"]}

def _allowed_agg(table_key):
    return {a["key"]: a["sql"] for a in CONFIG[table_key]["aggregations"]}

def _allowed_filter(table_key):
    return {c["key"] for c in CONFIG[table_key]["filter_cols"]}


# ─────────────────────────────────────────────────────────────────────────────
#  GET /api/custom/config
# ─────────────────────────────────────────────────────────────────────────────
@custom_chart_bp.route("/api/custom/config")
def get_config():
    return jsonify(CONFIG)


# ─────────────────────────────────────────────────────────────────────────────
#  GET /api/custom/filter-values?table=notifications&col=location
# ─────────────────────────────────────────────────────────────────────────────
@custom_chart_bp.route("/api/custom/filter-values")
def filter_values():
    table_key = request.args.get("table", "")
    col       = request.args.get("col", "")

    if table_key not in CONFIG:
        return jsonify({"error": "Invalid table"}), 400
    if col not in _allowed_filter(table_key):
        return jsonify({"error": "Invalid column"}), 400

    table = CONFIG[table_key]["table"]
    try:
        with db_cursor() as cur:
            cur.execute(
                f"SELECT DISTINCT {col} FROM {table} "
                f"WHERE {col} IS NOT NULL AND {col} != '' "
                f"ORDER BY {col} LIMIT 200"
            )
            values = [r[col] for r in cur.fetchall()]
        return jsonify(values)
    except Exception as e:
        print(f"[CUSTOM FILTER VALUES ERROR] {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  POST /api/custom/chart
# ─────────────────────────────────────────────────────────────────────────────
@custom_chart_bp.route("/api/custom/chart", methods=["POST"])
def build_chart():
    """
    Request body (JSON):
    {
        "table":      "notifications" | "work_orders",
        "x_col":      "notif_type",
        "agg":        "count",
        "group_col":  "criticality"  (optional, untuk legend/warna),
        "filters":    [{"col": "location", "val": "RU3"}],
        "top_n":      20             (optional, default 20, max 50)
    }
    """
    body      = request.get_json(force=True) or {}
    table_key = body.get("table", "notifications")
    x_col     = body.get("x_col", "")
    agg_key   = body.get("agg", "count")
    group_col = body.get("group_col") or None
    filters   = body.get("filters", [])
    top_n     = min(int(body.get("top_n", 20)), 50)

    # ── Validasi ──────────────────────────────────────────────────────────────
    if table_key not in CONFIG:
        return jsonify({"error": "table tidak valid"}), 400
    if x_col not in _allowed_x(table_key):
        return jsonify({"error": f"x_col tidak valid: {x_col}"}), 400
    if agg_key not in _allowed_agg(table_key):
        return jsonify({"error": f"aggregasi tidak valid: {agg_key}"}), 400
    if group_col and group_col not in _allowed_x(table_key):
        return jsonify({"error": f"group_col tidak valid: {group_col}"}), 400
    if group_col and group_col == x_col:
        return jsonify({"error": "group_col tidak boleh sama dengan x_col"}), 400

    table   = CONFIG[table_key]["table"]
    agg_sql = _allowed_agg(table_key)[agg_key]
    agg_lbl = next(a["label"] for a in CONFIG[table_key]["aggregations"] if a["key"] == agg_key)
    x_lbl   = next(c["label"] for c in CONFIG[table_key]["x_cols"] if c["key"] == x_col)

    # ── Build WHERE ───────────────────────────────────────────────────────────
    where_parts = []
    params      = []
    for f in filters:
        fcol = f.get("col", "")
        fval = f.get("val", "")
        if not fcol or fval == "" or fval is None:
            continue
        if fcol not in _allowed_filter(table_key):
            continue
        where_parts.append(f"{fcol} = %s")
        params.append(str(fval))

    where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

    # ── Build SQL ─────────────────────────────────────────────────────────────
    if group_col:
        g_lbl = next(c["label"] for c in CONFIG[table_key]["x_cols"] if c["key"] == group_col)
        sql = (
            f"SELECT {x_col}, {group_col}, {agg_sql} AS value "
            f"FROM {table} {where_sql} "
            f"GROUP BY {x_col}, {group_col} "
            f"ORDER BY {x_col}, value DESC"
        )
    else:
        sql = (
            f"SELECT {x_col}, {agg_sql} AS value "
            f"FROM {table} {where_sql} "
            f"GROUP BY {x_col} "
            f"ORDER BY value DESC "
            f"LIMIT {top_n}"
        )

    # ── Execute ───────────────────────────────────────────────────────────────
    try:
        with db_cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = []
            for r in cur.fetchall():
                row = dict(r)
                for k, v in row.items():
                    if v is None:
                        row[k] = "—"
                    elif hasattr(v, "__float__"):
                        row[k] = round(float(v), 2)
                    elif hasattr(v, "isoformat"):
                        row[k] = v.isoformat()
                rows.append(row)
    except Exception as e:
        print(f"[CUSTOM CHART SQL ERROR] {traceback.format_exc()}")
        return jsonify({"error": str(e)}), 500

    # ── Format untuk Chart.js ─────────────────────────────────────────────────
    if group_col:
        x_vals  = list(dict.fromkeys(str(r[x_col]) for r in rows))   # ordered unique
        groups  = sorted(set(str(r[group_col]) for r in rows))
        datasets = []
        for g in groups:
            data = [
                next((r["value"] for r in rows if str(r[x_col]) == x and str(r[group_col]) == g), 0)
                for x in x_vals
            ]
            datasets.append({"label": g, "data": data})
        return jsonify({
            "labels":    x_vals,
            "datasets":  datasets,
            "x_label":   x_lbl,
            "y_label":   agg_lbl,
            "group_label": g_lbl,
            "grouped":   True,
            "total_rows": len(rows),
        })
    else:
        return jsonify({
            "labels":   [str(r[x_col]) for r in rows],
            "datasets": [{"label": agg_lbl, "data": [r["value"] for r in rows]}],
            "x_label":  x_lbl,
            "y_label":  agg_lbl,
            "grouped":  False,
            "total_rows": len(rows),
        })
