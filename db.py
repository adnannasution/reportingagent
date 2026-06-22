"""
db.py — Koneksi PostgreSQL + Auto Migrasi Tabel
"""

import os
import psycopg2
import psycopg2.extras
from contextlib import contextmanager

DATABASE_URL = os.getenv("DATABASE_URL", "")


def get_conn():
    url = DATABASE_URL.replace("postgres://", "postgresql://", 1)
    return psycopg2.connect(url, sslmode="require")


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
    migrations = [
        # ── Existing tables ───────────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS reports (
            id         SERIAL PRIMARY KEY,
            type       VARCHAR(10) NOT NULL,
            content    TEXT        NOT NULL,
            created_at TIMESTAMP   DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS push_tokens (
            id         SERIAL PRIMARY KEY,
            token      TEXT UNIQUE NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS memos (
            id                SERIAL PRIMARY KEY,
            title             VARCHAR(255) NOT NULL,
            source_report_ids INTEGER[]    DEFAULT '{}',
            content           TEXT         NOT NULL,
            created_at        TIMESTAMP    DEFAULT NOW()
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS talking_points (
            id                SERIAL PRIMARY KEY,
            title             VARCHAR(255) NOT NULL,
            source_report_ids INTEGER[]    DEFAULT '{}',
            content           TEXT         NOT NULL,
            created_at        TIMESTAMP    DEFAULT NOW()
        );
        """,

        # ── SAP Notifications (IW29) ──────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS sap_notifications (
            id               SERIAL PRIMARY KEY,
            notif_type       VARCHAR(10),
            notif_date       DATE,
            notification     VARCHAR(20),
            system_status    VARCHAR(50),
            req_start        DATE,
            required_end     DATE,
            main_workctr     VARCHAR(30),
            planner_group    VARCHAR(10),
            description      TEXT,
            order_no         VARCHAR(20),
            location         VARCHAR(50),
            functional_loc   VARCHAR(50),
            equipment        VARCHAR(50),
            criticality      VARCHAR(5),
            maint_plant      VARCHAR(10),
            has_long_text    BOOLEAN DEFAULT FALSE,
            upload_batch     VARCHAR(50),
            uploaded_at      TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_sap_notif_status ON sap_notifications(system_status);",
        "CREATE INDEX IF NOT EXISTS idx_sap_notif_eq ON sap_notifications(equipment);",
        "CREATE INDEX IF NOT EXISTS idx_sap_notif_batch ON sap_notifications(upload_batch);",

        # ── SAP Work Orders (IW39 all PT types) ───────────────────
        """
        CREATE TABLE IF NOT EXISTS sap_work_orders (
            id               SERIAL PRIMARY KEY,
            plant            VARCHAR(10),
            created_on       DATE,
            changed_on       DATE,
            bas_start_date   DATE,
            basic_fin_date   DATE,
            notification     VARCHAR(20),
            order_no         VARCHAR(20),
            superior_order   VARCHAR(20),
            description      TEXT,
            functional_loc   VARCHAR(50),
            location         VARCHAR(50),
            equipment        VARCHAR(50),
            criticality      VARCHAR(5),
            user_status      VARCHAR(20),
            system_status    VARCHAR(100),
            planner_group    VARCHAR(10),
            total_plan_cost  NUMERIC(18,2),
            total_act_cost   NUMERIC(18,2),
            main_workctr     VARCHAR(30),
            po_number        VARCHAR(20),
            actual_finish    DATE,
            actual_release   DATE,
            order_type       VARCHAR(10),
            priority         VARCHAR(5),
            maint_act_type   VARCHAR(10),
            upload_batch     VARCHAR(50),
            uploaded_at      TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_sap_wo_status ON sap_work_orders(system_status);",
        "CREATE INDEX IF NOT EXISTS idx_sap_wo_eq ON sap_work_orders(equipment);",
        "CREATE INDEX IF NOT EXISTS idx_sap_wo_type ON sap_work_orders(order_type);",
        "CREATE INDEX IF NOT EXISTS idx_sap_wo_batch ON sap_work_orders(upload_batch);",

        # ── SAP BOM (Bill of Materials) ───────────────────────────
        """
        CREATE TABLE IF NOT EXISTS sap_bom (
            id               SERIAL PRIMARY KEY,
            equipment        VARCHAR(50),
            equipment_desc   TEXT,
            material         VARCHAR(30),
            plant            VARCHAR(10),
            usage            VARCHAR(5),
            item_node        VARCHAR(10),
            bom_category     VARCHAR(5),
            equip_category   VARCHAR(5),
            criticality      VARCHAR(5),
            alternative      VARCHAR(5),
            component        VARCHAR(30),
            component_desc   TEXT,
            mfr_part_number  VARCHAR(100),
            old_matl_number  VARCHAR(50),
            material_type    VARCHAR(10),
            item             VARCHAR(10),
            item_category    VARCHAR(5),
            quantity         NUMERIC(18,3),
            component_unit   VARCHAR(10),
            assembly         VARCHAR(50),
            sort_string      VARCHAR(50),
            spare_part_id    VARCHAR(10),
            item_text        TEXT,
            cost_element     VARCHAR(20),
            purch_group      VARCHAR(10),
            valid_from       DATE,
            valid_to         DATE,
            upload_batch     VARCHAR(50),
            uploaded_at      TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_sap_bom_equipment ON sap_bom(equipment);",
        "CREATE INDEX IF NOT EXISTS idx_sap_bom_component ON sap_bom(component);",
        "CREATE INDEX IF NOT EXISTS idx_sap_bom_batch ON sap_bom(upload_batch);",

        # ── SAP CJI3 (Project Actual Cost Line Items) ─────────────
        """
        CREATE TABLE IF NOT EXISTS sap_cji3 (
            id                 SERIAL PRIMARY KEY,
            project_definition VARCHAR(50),
            wbs_element        VARCHAR(50),
            posting_date       DATE,
            period              VARCHAR(5),
            document_date      DATE,
            object             VARCHAR(30),
            document_number    VARCHAR(30),
            ref_document_number VARCHAR(30),
            cost_element       VARCHAR(20),
            fiscal_year        VARCHAR(5),
            cost_element_name  VARCHAR(100),
            co_object_name     TEXT,
            name               TEXT,
            original_bus_trans VARCHAR(50),
            object_type        VARCHAR(10),
            order_no           VARCHAR(20),
            purchasing_document VARCHAR(30),
            purchase_order_text TEXT,
            transaction_currency VARCHAR(10),
            value_trancurr     NUMERIC(18,2),
            report_currency    VARCHAR(10),
            val_in_rep_cur     NUMERIC(18,2),
            object_currency    VARCHAR(10),
            value_in_obj_crcy  NUMERIC(18,2),
            user_name          VARCHAR(50),
            material           VARCHAR(30),
            material_description TEXT,
            total_quantity     NUMERIC(18,3),
            unit_of_measure    VARCHAR(10),
            upload_batch       VARCHAR(50),
            uploaded_at        TIMESTAMP DEFAULT NOW()
        );
        """,
        "CREATE INDEX IF NOT EXISTS idx_sap_cji3_project ON sap_cji3(project_definition);",
        "CREATE INDEX IF NOT EXISTS idx_sap_cji3_wbs ON sap_cji3(wbs_element);",
        "CREATE INDEX IF NOT EXISTS idx_sap_cji3_batch ON sap_cji3(upload_batch);",

        # ── Control Tower outputs ─────────────────────────────────
        """
        CREATE TABLE IF NOT EXISTS control_tower_outputs (
            id           SERIAL PRIMARY KEY,
            output_type  VARCHAR(30) NOT NULL,
            title        VARCHAR(255),
            content      TEXT NOT NULL,
            batch_ref    VARCHAR(50),
            created_at   TIMESTAMP DEFAULT NOW()
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


# ── Reports ───────────────────────────────────────────────────────────────────
def fetch_reports(report_type=None, limit=50):
    with db_cursor() as cur:
        if report_type:
            cur.execute(
                "SELECT id, type, LEFT(content,200) AS preview, created_at "
                "FROM reports WHERE type=%s ORDER BY created_at DESC LIMIT %s",
                (report_type, limit))
        else:
            cur.execute(
                "SELECT id, type, LEFT(content,200) AS preview, created_at "
                "FROM reports ORDER BY created_at DESC LIMIT %s", (limit,))
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
            (ids,))
        return cur.fetchall()

# ── Memos ─────────────────────────────────────────────────────────────────────
def save_memo(title, source_ids, content):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO memos (title, source_report_ids, content) VALUES (%s,%s,%s) RETURNING id",
            (title, source_ids, content))
        return cur.fetchone()["id"]

def fetch_memos(limit=50):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, source_report_ids, LEFT(content,200) AS preview, created_at "
            "FROM memos ORDER BY created_at DESC LIMIT %s", (limit,))
        return cur.fetchall()

def fetch_memo_detail(memo_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM memos WHERE id=%s", (memo_id,))
        return cur.fetchone()

# ── Talking Points ────────────────────────────────────────────────────────────
def save_talking_points(title, source_ids, content):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO talking_points (title, source_report_ids, content) VALUES (%s,%s,%s) RETURNING id",
            (title, source_ids, content))
        return cur.fetchone()["id"]

def fetch_talking_points(limit=50):
    with db_cursor() as cur:
        cur.execute(
            "SELECT id, title, source_report_ids, LEFT(content,200) AS preview, created_at "
            "FROM talking_points ORDER BY created_at DESC LIMIT %s", (limit,))
        return cur.fetchall()

def fetch_talking_points_detail(tp_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM talking_points WHERE id=%s", (tp_id,))
        return cur.fetchone()

# ── SAP Upload helpers ────────────────────────────────────────────────────────
def clear_sap_batch(batch_id: str, table: str):
    with db_cursor() as cur:
        if batch_id == "ALL":
            cur.execute(f"TRUNCATE TABLE {table}")
        else:
            cur.execute(f"DELETE FROM {table} WHERE upload_batch=%s", (batch_id,))

def insert_sap_notifications(rows: list, batch_id: str):
    with db_cursor() as cur:
        cur.executemany("""
            INSERT INTO sap_notifications
            (notif_type,notif_date,notification,system_status,req_start,required_end,
             main_workctr,planner_group,description,order_no,location,functional_loc,
             equipment,criticality,maint_plant,has_long_text,upload_batch)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)

def insert_sap_work_orders(rows: list, batch_id: str):
    with db_cursor() as cur:
        cur.executemany("""
            INSERT INTO sap_work_orders
            (plant,created_on,changed_on,bas_start_date,basic_fin_date,notification,
             order_no,superior_order,description,functional_loc,location,equipment,
             criticality,user_status,system_status,planner_group,total_plan_cost,
             total_act_cost,main_workctr,po_number,actual_finish,actual_release,
             order_type,priority,maint_act_type,upload_batch)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)

def insert_sap_bom(rows: list, batch_id: str):
    with db_cursor() as cur:
        cur.executemany("""
            INSERT INTO sap_bom
            (equipment,equipment_desc,material,plant,usage,item_node,bom_category,
             equip_category,criticality,alternative,component,component_desc,
             mfr_part_number,old_matl_number,material_type,item,item_category,
             quantity,component_unit,assembly,sort_string,spare_part_id,item_text,
             cost_element,purch_group,valid_from,valid_to,upload_batch)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)

def insert_sap_cji3(rows: list, batch_id: str):
    with db_cursor() as cur:
        cur.executemany("""
            INSERT INTO sap_cji3
            (project_definition,wbs_element,posting_date,period,document_date,object,
             document_number,ref_document_number,cost_element,fiscal_year,cost_element_name,
             co_object_name,name,original_bus_trans,object_type,order_no,purchasing_document,
             purchase_order_text,transaction_currency,value_trancurr,report_currency,
             val_in_rep_cur,object_currency,value_in_obj_crcy,user_name,material,
             material_description,total_quantity,unit_of_measure,upload_batch)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, rows)

def get_sap_summary():
    with db_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total, MAX(uploaded_at) AS last_upload FROM sap_notifications")
        notif = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS total, MAX(uploaded_at) AS last_upload FROM sap_work_orders")
        wo = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS total, MAX(uploaded_at) AS last_upload FROM sap_bom")
        bom = cur.fetchone()
        cur.execute("SELECT COUNT(*) AS total, MAX(uploaded_at) AS last_upload FROM sap_cji3")
        cji3 = cur.fetchone()
        return {"notifications": dict(notif), "work_orders": dict(wo), "bom": dict(bom), "cji3": dict(cji3)}

# ── Control Tower outputs ─────────────────────────────────────────────────────
def save_ct_output(output_type: str, title: str, content: str, batch_ref: str = ""):
    with db_cursor() as cur:
        cur.execute(
            "INSERT INTO control_tower_outputs (output_type,title,content,batch_ref) VALUES (%s,%s,%s,%s) RETURNING id",
            (output_type, title, content, batch_ref))
        return cur.fetchone()["id"]

def fetch_ct_outputs(output_type=None, limit=50):
    with db_cursor() as cur:
        if output_type:
            cur.execute(
                "SELECT id, output_type, title, LEFT(content,200) AS preview, created_at "
                "FROM control_tower_outputs WHERE output_type=%s ORDER BY created_at DESC LIMIT %s",
                (output_type, limit))
        else:
            cur.execute(
                "SELECT id, output_type, title, LEFT(content,200) AS preview, created_at "
                "FROM control_tower_outputs ORDER BY created_at DESC LIMIT %s", (limit,))
        return cur.fetchall()

def fetch_ct_output_detail(ct_id):
    with db_cursor() as cur:
        cur.execute("SELECT * FROM control_tower_outputs WHERE id=%s", (ct_id,))
        return cur.fetchone()

def get_sap_data_for_agent():
    """Ambil data SAP yang relevan untuk Control Tower Agent."""
    with db_cursor() as cur:
        # Notifikasi OSNO belum ada WO (backlog)
        cur.execute("""
            SELECT notif_type, notification, system_status, req_start, required_end,
                   main_workctr, description, equipment, functional_loc, criticality, location
            FROM sap_notifications
            WHERE (order_no IS NULL OR order_no = '')
              AND system_status ILIKE '%OSNO%'
            ORDER BY required_end ASC NULLS LAST LIMIT 50
        """)
        backlog_notif = cur.fetchall()

        # Notifikasi overdue (req end lewat, belum WO)
        cur.execute("""
            SELECT notif_type, notification, system_status, req_start, required_end,
                   description, equipment, criticality, location
            FROM sap_notifications
            WHERE (order_no IS NULL OR order_no = '')
              AND required_end < CURRENT_DATE
            ORDER BY required_end ASC LIMIT 30
        """)
        overdue_notif = cur.fetchall()

        # WO stagnant (REL tapi belum actual finish, fin date lewat)
        cur.execute("""
            SELECT order_no, order_type, system_status, bas_start_date, basic_fin_date,
                   description, equipment, functional_loc, criticality, location,
                   main_workctr, actual_release, actual_finish
            FROM sap_work_orders
            WHERE system_status ILIKE '%REL%'
              AND (actual_finish IS NULL)
            ORDER BY basic_fin_date ASC NULLS LAST LIMIT 50
        """)
        stagnant_wo = cur.fetchall()

        # WO overdue (fin date lewat, belum TECO/CLSD)
        cur.execute("""
            SELECT order_no, order_type, system_status, basic_fin_date,
                   description, equipment, criticality, location, main_workctr
            FROM sap_work_orders
            WHERE basic_fin_date < CURRENT_DATE
              AND system_status NOT ILIKE '%TECO%'
              AND system_status NOT ILIKE '%CLSD%'
            ORDER BY basic_fin_date ASC LIMIT 30
        """)
        overdue_wo = cur.fetchall()

        # WO CRTD (belum release)
        cur.execute("""
            SELECT order_no, order_type, system_status, bas_start_date, basic_fin_date,
                   description, equipment, criticality, location, main_workctr
            FROM sap_work_orders
            WHERE system_status ILIKE '%CRTD%'
              AND system_status NOT ILIKE '%REL%'
            ORDER BY bas_start_date ASC NULLS LAST LIMIT 20
        """)
        pending_release = cur.fetchall()

        # Summary per order type
        cur.execute("""
            SELECT order_type,
                   COUNT(*) AS total,
                   SUM(CASE WHEN system_status ILIKE '%REL%' AND actual_finish IS NULL THEN 1 ELSE 0 END) AS stagnant,
                   SUM(CASE WHEN system_status ILIKE '%TECO%' THEN 1 ELSE 0 END) AS teco,
                   SUM(CASE WHEN system_status ILIKE '%CLSD%' THEN 1 ELSE 0 END) AS closed,
                   SUM(CASE WHEN basic_fin_date < CURRENT_DATE
                             AND system_status NOT ILIKE '%TECO%'
                             AND system_status NOT ILIKE '%CLSD%' THEN 1 ELSE 0 END) AS overdue
            FROM sap_work_orders
            GROUP BY order_type ORDER BY order_type
        """)
        wo_summary = cur.fetchall()

        # Summary notif per status
        cur.execute("""
            SELECT system_status, COUNT(*) AS total,
                   SUM(CASE WHEN order_no IS NULL OR order_no='' THEN 1 ELSE 0 END) AS no_wo
            FROM sap_notifications
            GROUP BY system_status ORDER BY total DESC
        """)
        notif_summary = cur.fetchall()

        # Repeated notif pada equipment yang sama
        cur.execute("""
            SELECT equipment, COUNT(*) AS notif_count,
                   STRING_AGG(DISTINCT system_status, ', ') AS statuses,
                   MAX(required_end) AS latest_req_end
            FROM sap_notifications
            WHERE equipment IS NOT NULL AND equipment != ''
            GROUP BY equipment
            HAVING COUNT(*) > 1
            ORDER BY notif_count DESC LIMIT 15
        """)
        repeated_eq = cur.fetchall()

        return {
            "backlog_notifications": [dict(r) for r in backlog_notif],
            "overdue_notifications": [dict(r) for r in overdue_notif],
            "stagnant_wo": [dict(r) for r in stagnant_wo],
            "overdue_wo": [dict(r) for r in overdue_wo],
            "pending_release_wo": [dict(r) for r in pending_release],
            "wo_summary_by_type": [dict(r) for r in wo_summary],
            "notification_summary": [dict(r) for r in notif_summary],
            "repeated_equipment": [dict(r) for r in repeated_eq],
        }