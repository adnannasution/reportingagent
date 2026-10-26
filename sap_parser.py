"""
sap_parser.py — Parse Excel SAP (IW29 / IW39) ke format DB
Support: IW29 (Notification), IW39 PT02/PT03/PT05/PT08 (Work Orders)
"""

import re
import openpyxl
from datetime import datetime, date, time


def to_date(val):
    if val is None:
        return None
    if isinstance(val, (datetime, date)):
        return val.date() if isinstance(val, datetime) else val
    return None

def to_time(val):
    """Jam dari sel Excel: datetime.time, datetime, atau teks 'HH:MM[:SS]'."""
    if isinstance(val, datetime):
        return val.time()
    if isinstance(val, time):
        return val
    if isinstance(val, str):
        m = re.match(r'^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$', val)
        if m and int(m.group(1)) < 24 and int(m.group(2)) < 60:
            return time(int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
    return None

def to_timestamp(day_val, time_val):
    """Tanggal + jam (jam boleh kosong = 00:00) menjadi datetime."""
    d = to_date(day_val)
    if d is None:
        return None
    return datetime.combine(d, to_time(time_val) or time(0, 0))

def to_str(val):
    if val is None:
        return None
    return str(val).strip() or None

def to_float(val):
    if val is None:
        return None
    try:
        return float(val)
    except:
        return None


def detect_file_type(header: tuple) -> str:
    """Deteksi tipe file dari header kolom."""
    cols = [str(c).strip() if c else '' for c in header]
    if 'Notifictn type' in cols or 'Notification' in cols and 'Order Type' not in cols:
        return 'notification'
    if 'Order Type' in cols and 'Bas. start date' in cols:
        return 'work_order'
    if 'BOM category' in cols and 'Component' in cols:
        return 'bom'
    if 'WBS Element' in cols and 'Cost Element' in cols and 'Project Definition' in cols:
        return 'cji3'
    return 'unknown'


def parse_notification_file(filepath: str, batch_id: str) -> list:
    """Parse IW29 Excel → list of tuples untuk insert."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c).strip() if c else '' for c in rows[0]]

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    # Kolom opsional yang namanya berbeda antar-varian layout IW29: dicocokkan tanpa beda huruf/spasi/tanda baca.
    kunci = [re.sub(r'[^a-z0-9]', '', h.lower()) for h in header]

    def col_any(*names):
        for n in names:
            k = re.sub(r'[^a-z0-9]', '', n.lower())
            if k in kunci:
                return kunci.index(k)
        return None

    def val(idx, r):
        return r[idx] if idx is not None and idx < len(r) else None

    # Prioritas: beberapa layout IW29 punya dua kolom bernama "Priority" (teks mis. "-Routine-1 (RAM 3)"
    # dan kode mis. "3", urutannya bisa berbeda). Kode = kolom yang isinya pendek (<= 2 karakter).
    def pendek(idx):
        isi = [str(r[idx]).strip() for r in rows[1:201] if idx < len(r) and r[idx] not in (None, '')]
        isi = [x for x in isi if x]
        return bool(isi) and sum(len(x) <= 2 for x in isi) * 2 >= len(isi)

    prio_cols = [i for i, k in enumerate(kunci) if k == 'priority']
    c_prio = next((i for i in prio_cols if pendek(i)), None)
    c_prio_teks = col_any('Priority text', 'Priority.1', 'Prio. text')
    if c_prio_teks is None:
        c_prio_teks = next((i for i in prio_cols if i != c_prio), None)
    if c_prio is None and len(prio_cols) == 1 and c_prio_teks != prio_cols[0]:
        c_prio = prio_cols[0]
    c_mal_start = col_any('Malfunct.start', 'Malfunction start', 'Start of Malfunction', 'Malfunction Start Date')
    c_mal_end = col_any('Malfunct.end', 'Malfunction end', 'End of Malfunction', 'Malfunction End Date')
    # Jam malfunction: di layout RU7 "Start Malfn (T)" dan "Malfunction end" (berisi jam, sedangkan
    # tanggal selesai di "Malfunct.end"). Kolom jam tidak boleh sama dengan kolom tanggal.
    c_mal_start_t = col_any('Start Malfn (T)', 'Malfunct.start time', 'Malfunction start time', 'Start time of malfunction')
    c_mal_end_t = col_any('End Malfn (T)', 'Malfunct.end time', 'Malfunction end time', 'End time of malfunction',
                          'Malfunction end')
    if c_mal_start_t == c_mal_start:
        c_mal_start_t = None
    if c_mal_end_t == c_mal_end:
        c_mal_end_t = None
    c_breakdown = col_any('Breakdown', 'Breakdown Indicator', 'Breakdown indic.')
    c_breakdown_dur = col_any('Breakdown dur.', 'Breakdown duration', 'Breakdown Dur')

    results = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue

        has_long = False
        lt_idx = col('Long text')
        if lt_idx is not None and r[lt_idx]:
            has_long = str(r[lt_idx]).strip() in ('X', 'x', '1', 'True')

        results.append((
            to_str(r[col('Notifictn type')] if col('Notifictn type') is not None else None),
            to_date(r[col('Notif.date')] if col('Notif.date') is not None else None),
            to_str(r[col('Notification')] if col('Notification') is not None else None),
            to_str(r[col('System status')] if col('System status') is not None else None),
            to_date(r[col('Req. start')] if col('Req. start') is not None else None),
            to_date(r[col('Required End')] if col('Required End') is not None else None),
            to_str(r[col('Main WorkCtr')] if col('Main WorkCtr') is not None else None),
            to_str(r[col('Planner group')] if col('Planner group') is not None else None),
            to_str(r[col('Description')] if col('Description') is not None else None),
            to_str(r[col('Order')] if col('Order') is not None else None),
            to_str(r[col('Location')] if col('Location') is not None else None),
            to_str(r[col('Functional Loc.')] if col('Functional Loc.') is not None else None),
            to_str(r[col('Equipment')] if col('Equipment') is not None else None),
            to_str(r[col('Criticallity')] if col('Criticallity') is not None else None),
            to_str(r[col('MaintPlant')] if col('MaintPlant') is not None else None),
            has_long,
            batch_id,
            to_str(val(c_prio, r)),
            to_str(val(c_prio_teks, r)),
            to_date(val(c_mal_start, r)),
            to_date(val(c_mal_end, r)),
            (str(val(c_breakdown, r)).strip().upper() in ('X', '1', 'TRUE', 'YES', 'Y'))
            if val(c_breakdown, r) is not None else None,
            to_timestamp(val(c_mal_start, r), val(c_mal_start_t, r)),
            to_timestamp(val(c_mal_end, r), val(c_mal_end_t, r)),
            to_float(val(c_breakdown_dur, r)),
        ))
    return results


def parse_work_order_file(filepath: str, batch_id: str) -> list:
    """Parse IW39 Excel → list of tuples untuk insert."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c).strip() if c else '' for c in rows[0]]

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    results = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue

        # Ambil status utama dari system_status
        sys_st = to_str(r[col('System status')] if col('System status') is not None else None)
        user_st_raw = r[col('User status')] if col('User status') is not None else None
        user_st = to_str(user_st_raw)

        results.append((
            to_str(r[col('Plant')] if col('Plant') is not None else None),
            to_date(r[col('Created on')] if col('Created on') is not None else None),
            to_date(r[col('Changed on')] if col('Changed on') is not None else None),
            to_date(r[col('Bas. start date')] if col('Bas. start date') is not None else None),
            to_date(r[col('Basic fin. date')] if col('Basic fin. date') is not None else None),
            to_str(r[col('Notification')] if col('Notification') is not None else None),
            to_str(r[col('Order')] if col('Order') is not None else None),
            to_str(r[col('Superior order')] if col('Superior order') is not None else None),
            to_str(r[col('Description')] if col('Description') is not None else None),
            to_str(r[col('Functional Loc.')] if col('Functional Loc.') is not None else None),
            to_str(r[col('Location')] if col('Location') is not None else None),
            to_str(r[col('Equipment')] if col('Equipment') is not None else None),
            to_str(r[col('Criticallity')] if col('Criticallity') is not None else None),
            user_st,
            sys_st,
            to_str(r[col('Planner group')] if col('Planner group') is not None else None),
            to_float(r[col('TotalPlnndCosts')] if col('TotalPlnndCosts') is not None else None),
            to_float(r[col('Total act.costs')] if col('Total act.costs') is not None else None),
            to_str(r[col('Main WorkCtr')] if col('Main WorkCtr') is not None else None),
            to_str(r[col('PO number')] if col('PO number') is not None else None),
            to_date(r[col('Actual Finish')] if col('Actual Finish') is not None else None),
            to_date(r[col('Actual release')] if col('Actual release') is not None else None),
            to_str(r[col('Order Type')] if col('Order Type') is not None else None),
            to_str(r[col('Priority')] if col('Priority') is not None else None),
            to_str(r[col('MaintActivType')] if col('MaintActivType') is not None else None),
            to_str(r[col('Res./Purc. req.')] if col('Res./Purc. req.') is not None else None),
            to_str(r[col('Cost Center')] if col('Cost Center') is not None else None),
            to_str(r[col('WBS element')] if col('WBS element') is not None else None),
            batch_id,
        ))
    return results


def parse_bom_file(filepath: str, batch_id: str) -> list:
    """Parse BOM Excel → list of tuples untuk insert."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c).strip() if c else '' for c in rows[0]]

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    # Kolom Description muncul dua kali (equipment & component), ambil index keduanya
    desc_indices = [i for i, h in enumerate(header) if h == 'Description']
    eq_desc_idx   = desc_indices[0] if len(desc_indices) > 0 else None
    comp_desc_idx = desc_indices[1] if len(desc_indices) > 1 else None

    # Item text juga bisa muncul dua kali
    itext_indices = [i for i, h in enumerate(header) if h.lower() == 'item text']
    item_text_idx = itext_indices[0] if itext_indices else None

    results = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue
        results.append((
            to_str(r[col('Equipment')] if col('Equipment') is not None else None),
            to_str(r[eq_desc_idx] if eq_desc_idx is not None else None),
            to_str(r[col('Material')] if col('Material') is not None else None),
            to_str(r[col('Plant')] if col('Plant') is not None else None),
            to_str(r[col('Usage')] if col('Usage') is not None else None),
            to_str(r[col('Item node')] if col('Item node') is not None else None),
            to_str(r[col('BOM category')] if col('BOM category') is not None else None),
            to_str(r[col('EquipCategory')] if col('EquipCategory') is not None else None),
            to_str(r[col('Criticallity')] if col('Criticallity') is not None else None),
            to_str(r[col('Alternative')] if col('Alternative') is not None else None),
            to_str(r[col('Component')] if col('Component') is not None else None),
            to_str(r[comp_desc_idx] if comp_desc_idx is not None else None),
            to_str(r[col('Mfr Part Number')] if col('Mfr Part Number') is not None else None),
            to_str(r[col('Old matl number')] if col('Old matl number') is not None else None),
            to_str(r[col('Material Type')] if col('Material Type') is not None else None),
            to_str(r[col('Item')] if col('Item') is not None else None),
            to_str(r[col('Item Category')] if col('Item Category') is not None else None),
            to_float(r[col('Quantity')] if col('Quantity') is not None else None),
            to_str(r[col('Component unit')] if col('Component unit') is not None else None),
            to_str(r[col('Assembly')] if col('Assembly') is not None else None),
            to_str(r[col('Sort String')] if col('Sort String') is not None else None),
            to_str(r[col('Spare part ID')] if col('Spare part ID') is not None else None),
            to_str(r[item_text_idx] if item_text_idx is not None else None),
            to_str(r[col('Cost element')] if col('Cost element') is not None else None),
            to_str(r[col('Purch. Group')] if col('Purch. Group') is not None else None),
            to_date(r[col('Valid From')] if col('Valid From') is not None else None),
            to_date(r[col('Valid To')] if col('Valid To') is not None else None),
            batch_id,
        ))
    return results


def parse_bom_file(filepath: str, batch_id: str) -> list:
    """Parse BOM Excel → list of tuples untuk insert."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c).strip() if c else '' for c in rows[0]]

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    # Kolom Description muncul dua kali (equipment & component), ambil index keduanya
    desc_indices = [i for i, h in enumerate(header) if h == 'Description']
    eq_desc_idx   = desc_indices[0] if len(desc_indices) > 0 else None
    comp_desc_idx = desc_indices[1] if len(desc_indices) > 1 else None

    # Item text juga bisa muncul dua kali
    itext_indices = [i for i, h in enumerate(header) if h.lower() == 'item text']
    item_text_idx = itext_indices[0] if itext_indices else None

    results = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue
        results.append((
            to_str(r[col('Equipment')] if col('Equipment') is not None else None),
            to_str(r[eq_desc_idx] if eq_desc_idx is not None else None),
            to_str(r[col('Material')] if col('Material') is not None else None),
            to_str(r[col('Plant')] if col('Plant') is not None else None),
            to_str(r[col('Usage')] if col('Usage') is not None else None),
            to_str(r[col('Item node')] if col('Item node') is not None else None),
            to_str(r[col('BOM category')] if col('BOM category') is not None else None),
            to_str(r[col('EquipCategory')] if col('EquipCategory') is not None else None),
            to_str(r[col('Criticallity')] if col('Criticallity') is not None else None),
            to_str(r[col('Alternative')] if col('Alternative') is not None else None),
            to_str(r[col('Component')] if col('Component') is not None else None),
            to_str(r[comp_desc_idx] if comp_desc_idx is not None else None),
            to_str(r[col('Mfr Part Number')] if col('Mfr Part Number') is not None else None),
            to_str(r[col('Old matl number')] if col('Old matl number') is not None else None),
            to_str(r[col('Material Type')] if col('Material Type') is not None else None),
            to_str(r[col('Item')] if col('Item') is not None else None),
            to_str(r[col('Item Category')] if col('Item Category') is not None else None),
            to_float(r[col('Quantity')] if col('Quantity') is not None else None),
            to_str(r[col('Component unit')] if col('Component unit') is not None else None),
            to_str(r[col('Assembly')] if col('Assembly') is not None else None),
            to_str(r[col('Sort String')] if col('Sort String') is not None else None),
            to_str(r[col('Spare part ID')] if col('Spare part ID') is not None else None),
            to_str(r[item_text_idx] if item_text_idx is not None else None),
            to_str(r[col('Cost element')] if col('Cost element') is not None else None),
            to_str(r[col('Purch. Group')] if col('Purch. Group') is not None else None),
            to_date(r[col('Valid From')] if col('Valid From') is not None else None),
            to_date(r[col('Valid To')] if col('Valid To') is not None else None),
            batch_id,
        ))
    return results


def parse_cji3_file(filepath: str, batch_id: str) -> list:
    """Parse CJI3 (Project Actual Cost Line Items) Excel → list of tuples untuk insert."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    header = [str(c).strip() if c else '' for c in rows[0]]

    def col(name):
        try:
            return header.index(name)
        except ValueError:
            return None

    results = []
    for r in rows[1:]:
        if not any(c is not None for c in r):
            continue
        results.append((
            to_str(r[col('Project Definition')] if col('Project Definition') is not None else None),
            to_str(r[col('WBS Element')] if col('WBS Element') is not None else None),
            to_date(r[col('Posting Date')] if col('Posting Date') is not None else None),
            to_str(r[col('Period')] if col('Period') is not None else None),
            to_date(r[col('Document Date')] if col('Document Date') is not None else None),
            to_str(r[col('Object')] if col('Object') is not None else None),
            to_str(r[col('Document Number')] if col('Document Number') is not None else None),
            to_str(r[col('Ref Document Number')] if col('Ref Document Number') is not None else None),
            to_str(r[col('Cost Element')] if col('Cost Element') is not None else None),
            to_str(r[col('Fiscal Year')] if col('Fiscal Year') is not None else None),
            to_str(r[col('Cost element name')] if col('Cost element name') is not None else None),
            to_str(r[col('CO object name')] if col('CO object name') is not None else None),
            to_str(r[col('Name')] if col('Name') is not None else None),
            to_str(r[col('Original bus. trans')] if col('Original bus. trans') is not None else None),
            to_str(r[col('Object type')] if col('Object type') is not None else None),
            to_str(r[col('Order')] if col('Order') is not None else None),
            to_str(r[col('Purchasing Document')] if col('Purchasing Document') is not None else None),
            to_str(r[col('Purchase order text')] if col('Purchase order text') is not None else None),
            to_str(r[col('Transaction Currency')] if col('Transaction Currency') is not None else None),
            to_float(r[col('Value TranCurr')] if col('Value TranCurr') is not None else None),
            to_str(r[col('Report currency')] if col('Report currency') is not None else None),
            to_float(r[col('Val.in rep.cur.')] if col('Val.in rep.cur.') is not None else None),
            to_str(r[col('Object Currency')] if col('Object Currency') is not None else None),
            to_float(r[col('Value in Obj. Crcy')] if col('Value in Obj. Crcy') is not None else None),
            to_str(r[col('User Name')] if col('User Name') is not None else None),
            to_str(r[col('Material')] if col('Material') is not None else None),
            to_str(r[col('Material Description')] if col('Material Description') is not None else None),
            to_float(r[col('Total quantity')] if col('Total quantity') is not None else None),
            to_str(r[col('Unit of Measure')] if col('Unit of Measure') is not None else None),
            batch_id,
        ))
    return results


def parse_file(filepath: str, batch_id: str) -> dict:
    """Auto-detect dan parse file SAP Excel."""
    wb = openpyxl.load_workbook(filepath, read_only=True)
    ws = wb.active
    first_row = next(ws.iter_rows(max_row=1, values_only=True))
    wb.close()

    file_type = detect_file_type(first_row)

    if file_type == 'notification':
        rows = parse_notification_file(filepath, batch_id)
        return {"type": "notification", "rows": rows, "count": len(rows)}
    elif file_type == 'work_order':
        rows = parse_work_order_file(filepath, batch_id)
        return {"type": "work_order", "rows": rows, "count": len(rows)}
    elif file_type == 'bom':
        rows = parse_bom_file(filepath, batch_id)
        return {"type": "bom", "rows": rows, "count": len(rows)}
    elif file_type == 'cji3':
        rows = parse_cji3_file(filepath, batch_id)
        return {"type": "cji3", "rows": rows, "count": len(rows)}
    else:
        return {"type": "unknown", "rows": [], "count": 0}