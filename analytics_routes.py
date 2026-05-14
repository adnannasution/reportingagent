"""
analytics_routes.py — Flask Blueprint: SAP Analytics
Endpoints:
  GET /api/analytics/charts        → semua aggregate untuk chart (1 call)
  GET /api/analytics/detail        → paginated detail table per chart segment
"""

import math
from flask import Blueprint, request, jsonify
from db import db_cursor
from datetime import timedelta  # ← tambah di baris import

analytics_bp = Blueprint("analytics", __name__)


# ─────────────────────────────────────────────────────────────────────────────
#  /api/analytics/charts  — semua aggregate dalam 1 request
# ─────────────────────────────────────────────────────────────────────────────
@analytics_bp.route("/api/analytics/charts")
def get_charts():
    try:
        with db_cursor() as cur:
            results = {}

            # 1. Funnel: total notif → punya WO → REL → TECO/CLSD
            cur.execute("""
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN order_no IS NOT NULL AND order_no != '' THEN 1 ELSE 0 END) AS has_wo
                FROM sap_notifications
            """)
            row = cur.fetchone()
            results["funnel"] = {
                "total": row["total"],
                "has_wo": row["has_wo"],
                "rel": 0,
                "done": 0,
            }
            cur.execute("""
                SELECT
                    SUM(CASE WHEN w.system_status ILIKE '%REL%' THEN 1 ELSE 0 END) AS rel,
                    SUM(CASE WHEN w.system_status ILIKE '%TECO%'
                              OR w.system_status ILIKE '%CLSD%' THEN 1 ELSE 0 END) AS done
                FROM sap_notifications n
                JOIN sap_work_orders w ON n.order_no = w.order_no
                WHERE n.order_no IS NOT NULL AND n.order_no != ''
            """)
            r2 = cur.fetchone()
            if r2:
                results["funnel"]["rel"]  = r2["rel"]  or 0
                results["funnel"]["done"] = r2["done"] or 0

            # 2. Lead time (hari) notif → WO per notif_type x criticality
            cur.execute("""
                SELECT
                    n.notif_type,
                    n.criticality,
                    ROUND(AVG(w.created_on - n.notif_date))::INT AS avg_days,
                    COUNT(*) AS cnt
                FROM sap_notifications n
                JOIN sap_work_orders w ON n.order_no = w.order_no
                WHERE n.notif_date  IS NOT NULL
                  AND w.created_on  IS NOT NULL
                  AND w.created_on >= n.notif_date
                  AND n.criticality IN ('H','M','L')
                  AND n.notif_type  IN ('M1','M2','M3')
                GROUP BY n.notif_type, n.criticality
                ORDER BY n.notif_type, n.criticality
            """)
            results["leadtime"] = [dict(r) for r in cur.fetchall()]

            # 3. Overdue notif + status WO-nya
            cur.execute("""
                SELECT
                    n.notif_type,
                    CASE
                        WHEN n.order_no IS NULL OR n.order_no = ''            THEN 'no_wo'
                        WHEN w.system_status ILIKE '%TECO%'
                          OR w.system_status ILIKE '%CLSD%'                   THEN 'teco'
                        WHEN w.system_status ILIKE '%REL%'                    THEN 'rel'
                        ELSE 'crtd'
                    END AS wo_cat,
                    COUNT(*) AS cnt
                FROM sap_notifications n
                LEFT JOIN sap_work_orders w ON n.order_no = w.order_no
                WHERE n.required_end < CURRENT_DATE
                GROUP BY n.notif_type, wo_cat
                ORDER BY n.notif_type
            """)
            results["overdue"] = [dict(r) for r in cur.fetchall()]

            # 4. Bad actor equipment (banyak notif, WO masih stagnant)
            cur.execute("""
                SELECT
                    n.equipment,
                    COUNT(DISTINCT n.id) AS notif_cnt,
                    COUNT(DISTINCT CASE
                        WHEN w.system_status ILIKE '%REL%'
                         AND w.actual_finish IS NULL THEN w.id
                    END) AS stagnant_wo
                FROM sap_notifications n
                LEFT JOIN sap_work_orders w ON n.equipment = w.equipment
                WHERE n.equipment IS NOT NULL AND n.equipment != ''
                GROUP BY n.equipment
                HAVING COUNT(DISTINCT n.id) >= 3
                ORDER BY notif_cnt DESC
                LIMIT 10
            """)
            results["badactor"] = [dict(r) for r in cur.fetchall()]

            # 5. Trend bulanan: notif masuk vs WO selesai (6 bulan terakhir)
            cur.execute("""
                SELECT TO_CHAR(notif_date, 'YYYY-MM') AS month, COUNT(*) AS cnt
                FROM sap_notifications
                WHERE notif_date >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '5 months')
                GROUP BY month ORDER BY month
            """)
            results["trend_notif"] = [dict(r) for r in cur.fetchall()]

            cur.execute("""
                SELECT TO_CHAR(actual_finish, 'YYYY-MM') AS month, COUNT(*) AS cnt
                FROM sap_work_orders
                WHERE actual_finish >= DATE_TRUNC('month', CURRENT_DATE - INTERVAL '5 months')
                  AND (system_status ILIKE '%TECO%' OR system_status ILIKE '%CLSD%')
                GROUP BY month ORDER BY month
            """)
            results["trend_done"] = [dict(r) for r in cur.fetchall()]

            # 6. WO status per order type (stacked bar)
            cur.execute("""
                SELECT
                    order_type,
                    SUM(CASE WHEN system_status ILIKE '%CRTD%'
                              AND system_status NOT ILIKE '%REL%' THEN 1 ELSE 0 END) AS crtd,
                    SUM(CASE WHEN system_status ILIKE '%REL%'     THEN 1 ELSE 0 END) AS rel,
                    SUM(CASE WHEN system_status ILIKE '%TECO%'    THEN 1 ELSE 0 END) AS teco,
                    SUM(CASE WHEN system_status ILIKE '%CLSD%'    THEN 1 ELSE 0 END) AS clsd
                FROM sap_work_orders
                WHERE order_type IS NOT NULL AND order_type != ''
                GROUP BY order_type ORDER BY order_type
            """)
            results["wo_by_type"] = [dict(r) for r in cur.fetchall()]

            # 7. Distribusi status notifikasi
            cur.execute("""
                SELECT system_status, COUNT(*) AS cnt
                FROM sap_notifications
                WHERE system_status IS NOT NULL
                GROUP BY system_status ORDER BY cnt DESC LIMIT 8
            """)
            results["notif_status"] = [dict(r) for r in cur.fetchall()]

            # 8. Aging WO overdue (histogram bucket)
            cur.execute("""
                SELECT
                    CASE
                        WHEN CURRENT_DATE - basic_fin_date BETWEEN 1  AND 7   THEN '1-7 hari'
                        WHEN CURRENT_DATE - basic_fin_date BETWEEN 8  AND 30  THEN '8-30 hari'
                        WHEN CURRENT_DATE - basic_fin_date BETWEEN 31 AND 90  THEN '31-90 hari'
                        WHEN CURRENT_DATE - basic_fin_date BETWEEN 91 AND 180 THEN '91-180 hari'
                        ELSE '>180 hari'
                    END AS bucket,
                    COUNT(*) AS cnt
                FROM sap_work_orders
                WHERE basic_fin_date < CURRENT_DATE
                  AND system_status NOT ILIKE '%TECO%'
                  AND system_status NOT ILIKE '%CLSD%'
                GROUP BY bucket
                ORDER BY MIN(CURRENT_DATE - basic_fin_date)
            """)
            results["aging"] = [dict(r) for r in cur.fetchall()]

            # 9. Backlog notif per workcenter (top 10)
            cur.execute("""
                SELECT main_workctr AS workctr, COUNT(*) AS cnt
                FROM sap_notifications
                WHERE (order_no IS NULL OR order_no = '')
                  AND main_workctr IS NOT NULL AND main_workctr != ''
                GROUP BY main_workctr ORDER BY cnt DESC LIMIT 10
            """)
            results["backlog_workctr"] = [dict(r) for r in cur.fetchall()]

            return jsonify(results)

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  /api/analytics/detail  — detail table dengan server-side pagination
# ─────────────────────────────────────────────────────────────────────────────
@analytics_bp.route("/api/analytics/detail")
def analytics_detail():
    source   = request.args.get("source", "")
    page     = max(1, int(request.args.get("page", 1)))
    per_page = min(100, max(10, int(request.args.get("per_page", 25))))
    offset   = (page - 1) * per_page

    sql, params, columns, title = _build_detail_query(source, request.args)
    if not sql:
        return jsonify({"error": f"Unknown source: {source}"}), 400

    try:
        with db_cursor() as cur:
            # Total count (tanpa LIMIT)
            cur.execute(f"SELECT COUNT(*) AS n FROM ({sql}) AS _sub", params)
            total = cur.fetchone()["n"]

            # Data dengan pagination
            cur.execute(f"{sql} LIMIT %s OFFSET %s", (*params, per_page, offset))
            rows = []
            for row in cur.fetchall():
                r = dict(row)
                # Serialize dates dan Decimal
                for k, v in r.items():
                    if v is None:
                        r[k] = "—"
                    elif isinstance(v, timedelta):   # ← tambah baris ini
                        r[k] = v.days                # ← dan ini
                    elif hasattr(v, "isoformat"):
                        r[k] = v.isoformat()
                    elif hasattr(v, "__float__"):
                        r[k] = round(float(v), 2)
                rows.append(r)

        return jsonify({
            "title":       title,
            "columns":     columns,
            "rows":        rows,
            "total":       total,
            "page":        page,
            "per_page":    per_page,
            "total_pages": math.ceil(total / per_page) if total else 1,
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ─────────────────────────────────────────────────────────────────────────────
#  Query builder — dispatch per source
# ─────────────────────────────────────────────────────────────────────────────
def _build_detail_query(source, args):
    """
    Return (sql_string, params_tuple, columns_list, title_string)
    columns_list: list of dicts {key, label, type}
    """

    def col(key, label, typ="text"):
        return {"key": key, "label": label, "type": typ}

    NOTIF_BASE_COLS = [
        col("notification",  "Notif #",      "badge"),
        col("notif_type",    "Tipe",         "badge"),
        col("system_status", "Status Notif", "status"),
        col("criticality",   "Krit.",        "criticality"),
        col("description",   "Deskripsi",    "text"),
        col("equipment",     "Equipment",    "mono"),
        col("location",      "Lokasi",       "text"),
        col("required_end",  "Req. End",     "date"),
        col("order_no",      "Order #",      "mono"),
    ]

    WO_BASE_COLS = [
        col("order_no",        "Order #",       "badge"),
        col("order_type",      "Tipe",          "badge"),
        col("system_status",   "Status WO",     "status"),
        col("criticality",     "Krit.",         "criticality"),
        col("description",     "Deskripsi",     "text"),
        col("equipment",       "Equipment",     "mono"),
        col("location",        "Lokasi",        "text"),
        col("basic_fin_date",  "Fin. Date",     "date"),
        col("actual_finish",   "Actual Finish", "date"),
        col("main_workctr",    "Workcenter",    "text"),
    ]

    # ── Funnel ────────────────────────────────────────────────────────────────
    if source == "funnel":
        segment = args.get("segment", "no_wo")
        if segment == "no_wo":
            return (
                "SELECT notification,notif_type,system_status,criticality,"
                "LEFT(description,80) AS description,equipment,location,required_end,order_no "
                "FROM sap_notifications WHERE (order_no IS NULL OR order_no='') "
                "ORDER BY required_end ASC NULLS LAST",
                (), NOTIF_BASE_COLS, "Notifikasi belum ada WO",
            )
        if segment == "has_wo":
            return (
                "SELECT n.notification,n.notif_type,n.system_status,n.criticality,"
                "LEFT(n.description,80) AS description,n.equipment,n.location,"
                "n.required_end,n.order_no,w.system_status AS wo_status "
                "FROM sap_notifications n JOIN sap_work_orders w ON n.order_no=w.order_no "
                "WHERE n.order_no IS NOT NULL AND n.order_no!='' "
                "ORDER BY n.required_end ASC NULLS LAST",
                (),
                NOTIF_BASE_COLS + [col("wo_status", "Status WO", "status")],
                "Notifikasi dengan WO (joined)",
            )
        if segment == "rel":
            return (
                "SELECT n.notification,n.notif_type,n.criticality,"
                "LEFT(n.description,80) AS description,n.equipment,n.location,"
                "n.required_end,w.order_no,w.order_type,w.system_status AS wo_status,"
                "w.basic_fin_date,w.main_workctr "
                "FROM sap_notifications n JOIN sap_work_orders w ON n.order_no=w.order_no "
                "WHERE w.system_status ILIKE '%REL%' "
                "ORDER BY w.basic_fin_date ASC NULLS LAST",
                (),
                [
                    col("notification", "Notif #",    "badge"),
                    col("notif_type",   "Tipe Notif", "badge"),
                    col("criticality",  "Krit.",      "criticality"),
                    col("description",  "Deskripsi",  "text"),
                    col("equipment",    "Equipment",  "mono"),
                    col("location",     "Lokasi",     "text"),
                    col("order_no",     "Order #",    "badge"),
                    col("order_type",   "Tipe WO",    "badge"),
                    col("wo_status",    "Status WO",  "status"),
                    col("basic_fin_date", "Fin. Date","date"),
                    col("main_workctr", "Workcenter", "text"),
                ],
                "WO sedang REL (dari notif)",
            )
        if segment == "done":
            return (
                "SELECT n.notification,n.notif_type,n.criticality,"
                "LEFT(n.description,80) AS description,n.equipment,n.location,"
                "w.order_no,w.order_type,w.system_status AS wo_status,"
                "w.actual_finish,w.main_workctr "
                "FROM sap_notifications n JOIN sap_work_orders w ON n.order_no=w.order_no "
                "WHERE w.system_status ILIKE '%TECO%' OR w.system_status ILIKE '%CLSD%' "
                "ORDER BY w.actual_finish DESC NULLS LAST",
                (),
                [
                    col("notification", "Notif #",    "badge"),
                    col("notif_type",   "Tipe Notif", "badge"),
                    col("criticality",  "Krit.",      "criticality"),
                    col("description",  "Deskripsi",  "text"),
                    col("equipment",    "Equipment",  "mono"),
                    col("order_no",     "Order #",    "badge"),
                    col("order_type",   "Tipe WO",    "badge"),
                    col("wo_status",    "Status WO",  "status"),
                    col("actual_finish","Actual Fin.", "date"),
                    col("main_workctr", "Workcenter", "text"),
                ],
                "WO sudah TECO / CLSD",
            )

    # ── Lead time ─────────────────────────────────────────────────────────────
    if source == "leadtime":
        ntype = args.get("notif_type", "M1")
        crit  = args.get("criticality", "H")
        return (
            "SELECT n.notification,n.notif_type,n.criticality,"
            "LEFT(n.description,80) AS description,n.equipment,n.location,"
            "n.notif_date,w.order_no,w.created_on,"
            "(w.created_on - n.notif_date) AS lead_days "
            "FROM sap_notifications n JOIN sap_work_orders w ON n.order_no=w.order_no "
            "WHERE n.notif_date IS NOT NULL AND w.created_on IS NOT NULL "
            "  AND w.created_on >= n.notif_date "
            "  AND n.notif_type=%s AND n.criticality=%s "
            "ORDER BY lead_days DESC",
            (ntype, crit),
            [
                col("notification", "Notif #",    "badge"),
                col("notif_type",   "Tipe",       "badge"),
                col("criticality",  "Krit.",      "criticality"),
                col("description",  "Deskripsi",  "text"),
                col("equipment",    "Equipment",  "mono"),
                col("location",     "Lokasi",     "text"),
                col("notif_date",   "Tgl Notif",  "date"),
                col("order_no",     "Order #",    "badge"),
                col("created_on",   "WO Dibuat",  "date"),
                col("lead_days",    "Lead Time (hr)", "number"),
            ],
            f"Lead Time — {ntype} / Kritikalitas {crit}",
        )

    # ── Overdue notif + WO status ─────────────────────────────────────────────
    if source == "overdue":
        ntype  = args.get("notif_type", "M1")
        wo_cat = args.get("wo_cat", "no_wo")
        cat_where = {
            "no_wo": "(n.order_no IS NULL OR n.order_no='')",
            "crtd":  "w.system_status ILIKE '%CRTD%' AND w.system_status NOT ILIKE '%REL%'",
            "rel":   "w.system_status ILIKE '%REL%'",
            "teco":  "(w.system_status ILIKE '%TECO%' OR w.system_status ILIKE '%CLSD%')",
        }.get(wo_cat, "(n.order_no IS NULL OR n.order_no='')")
        return (
            f"SELECT n.notification,n.notif_type,n.system_status,n.criticality,"
            f"LEFT(n.description,80) AS description,n.equipment,n.location,"
            f"n.required_end,n.order_no,COALESCE(w.system_status,'—') AS wo_status "
            f"FROM sap_notifications n LEFT JOIN sap_work_orders w ON n.order_no=w.order_no "
            f"WHERE n.required_end < CURRENT_DATE AND n.notif_type=%s AND {cat_where} "
            f"ORDER BY n.required_end ASC",
            (ntype,),
            NOTIF_BASE_COLS + [col("wo_status", "Status WO", "status")],
            f"Notif Overdue {ntype} — WO {wo_cat.upper()}",
        )

    # ── Bad actor equipment ───────────────────────────────────────────────────
    if source == "badactor":
        equipment = args.get("equipment", "")
        return (
            "SELECT n.notification,n.notif_type,n.system_status,n.criticality,"
            "LEFT(n.description,80) AS description,n.equipment,n.location,n.required_end,"
            "n.order_no,COALESCE(w.order_type,'—') AS wo_type,"
            "COALESCE(w.system_status,'—') AS wo_status,w.basic_fin_date "
            "FROM sap_notifications n LEFT JOIN sap_work_orders w ON n.order_no=w.order_no "
            "WHERE n.equipment=%s ORDER BY n.required_end ASC NULLS LAST",
            (equipment,),
            [
                col("notification", "Notif #",    "badge"),
                col("notif_type",   "Tipe",       "badge"),
                col("system_status","Status Notif","status"),
                col("criticality",  "Krit.",      "criticality"),
                col("description",  "Deskripsi",  "text"),
                col("location",     "Lokasi",     "text"),
                col("required_end", "Req. End",   "date"),
                col("order_no",     "Order #",    "mono"),
                col("wo_type",      "Tipe WO",    "badge"),
                col("wo_status",    "Status WO",  "status"),
                col("basic_fin_date","Fin. Date", "date"),
            ],
            f"Bad Actor Equipment: {equipment}",
        )

    # ── Trend bulanan ─────────────────────────────────────────────────────────
    if source == "trend":
        month     = args.get("month", "")
        data_type = args.get("data_type", "notif")
        if data_type == "notif":
            return (
                "SELECT notification,notif_type,system_status,criticality,"
                "LEFT(description,80) AS description,equipment,location,"
                "notif_date,required_end,order_no "
                "FROM sap_notifications WHERE TO_CHAR(notif_date,'YYYY-MM')=%s "
                "ORDER BY notif_date DESC",
                (month,), NOTIF_BASE_COLS, f"Notifikasi masuk {month}",
            )
        else:
            return (
                "SELECT order_no,order_type,system_status,criticality,"
                "LEFT(description,80) AS description,equipment,location,"
                "basic_fin_date,actual_finish,main_workctr "
                "FROM sap_work_orders "
                "WHERE TO_CHAR(actual_finish,'YYYY-MM')=%s "
                "  AND (system_status ILIKE '%TECO%' OR system_status ILIKE '%CLSD%') "
                "ORDER BY actual_finish DESC",
                (month,), WO_BASE_COLS, f"WO selesai {month}",
            )

    # ── WO by order type × status ─────────────────────────────────────────────
    if source == "wo_by_type":
        order_type = args.get("order_type", "PT02")
        status     = args.get("status", "REL").lower()
        status_where = {
            "crtd": "system_status ILIKE '%CRTD%' AND system_status NOT ILIKE '%REL%'",
            "rel":  "system_status ILIKE '%REL%'",
            "teco": "system_status ILIKE '%TECO%'",
            "clsd": "system_status ILIKE '%CLSD%'",
        }.get(status, "system_status ILIKE '%REL%'")
        return (
            f"SELECT order_no,order_type,system_status,criticality,"
            f"LEFT(description,80) AS description,equipment,location,"
            f"bas_start_date,basic_fin_date,actual_finish,main_workctr,"
            f"total_plan_cost,total_act_cost "
            f"FROM sap_work_orders WHERE order_type=%s AND {status_where} "
            f"ORDER BY basic_fin_date ASC NULLS LAST",
            (order_type,),
            WO_BASE_COLS + [
                col("total_plan_cost", "Plan Cost", "currency"),
                col("total_act_cost",  "Act. Cost",  "currency"),
            ],
            f"WO {order_type} — Status {status.upper()}",
        )

    # ── Notif status distribution ─────────────────────────────────────────────
    if source == "notif_status":
        status = args.get("status", "OSNO")
        return (
            "SELECT notification,notif_type,system_status,criticality,"
            "LEFT(description,80) AS description,equipment,location,"
            "notif_date,required_end,order_no "
            "FROM sap_notifications WHERE system_status=%s "
            "ORDER BY required_end ASC NULLS LAST",
            (status,), NOTIF_BASE_COLS, f"Notifikasi status {status}",
        )

    # ── Aging WO overdue ──────────────────────────────────────────────────────
    if source == "aging":
        bucket = args.get("bucket", "31-90 hari")
        bucket_where = {
            "1-7 hari":    "CURRENT_DATE - basic_fin_date BETWEEN 1  AND 7",
            "8-30 hari":   "CURRENT_DATE - basic_fin_date BETWEEN 8  AND 30",
            "31-90 hari":  "CURRENT_DATE - basic_fin_date BETWEEN 31 AND 90",
            "91-180 hari": "CURRENT_DATE - basic_fin_date BETWEEN 91 AND 180",
            ">180 hari":   "CURRENT_DATE - basic_fin_date > 180",
        }.get(bucket, "CURRENT_DATE - basic_fin_date BETWEEN 31 AND 90")
        return (
            f"SELECT order_no,order_type,system_status,criticality,"
            f"LEFT(description,80) AS description,equipment,location,"
            f"basic_fin_date,(CURRENT_DATE - basic_fin_date) AS days_overdue,main_workctr "
            f"FROM sap_work_orders "
            f"WHERE basic_fin_date < CURRENT_DATE "
            f"  AND system_status NOT ILIKE '%TECO%' "
            f"  AND system_status NOT ILIKE '%CLSD%' "
            f"  AND {bucket_where} "
            f"ORDER BY days_overdue DESC",
            (),
            WO_BASE_COLS[:-1] + [col("days_overdue", "Hari Overdue", "number")],
            f"WO Overdue — {bucket}",
        )

    # ── Backlog per workcenter ────────────────────────────────────────────────
    if source == "backlog_workctr":
        workctr = args.get("workctr", "")
        return (
            "SELECT notification,notif_type,system_status,criticality,"
            "LEFT(description,80) AS description,equipment,location,"
            "required_end,main_workctr "
            "FROM sap_notifications "
            "WHERE (order_no IS NULL OR order_no='') AND main_workctr=%s "
            "ORDER BY required_end ASC NULLS LAST",
            (workctr,),
            [
                col("notification",  "Notif #",    "badge"),
                col("notif_type",    "Tipe",       "badge"),
                col("system_status", "Status",     "status"),
                col("criticality",   "Krit.",      "criticality"),
                col("description",   "Deskripsi",  "text"),
                col("equipment",     "Equipment",  "mono"),
                col("location",      "Lokasi",     "text"),
                col("required_end",  "Req. End",   "date"),
                col("main_workctr",  "Workcenter", "text"),
            ],
            f"Backlog Notif — Workcenter {workctr}",
        )

    return None, None, None, None
