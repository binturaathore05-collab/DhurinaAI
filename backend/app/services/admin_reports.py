"""Dhurina admin reports: sales of every teacher for any period, with the full split.

- period: any from/to date (Indian time), e.g. this month, last month, a quarter, a year
- by teacher: subscriptions, new vs renewals, paying students, total students, sales, Dhurina, teacher payout
- payments: every paid subscription (which student paid how much, to which teacher), paged + searchable
- trend: month by month totals
- export: Excel (Summary, By teacher, Payments, Monthly) and PDF
Built on plain SQL aggregates so it stays fast with many teachers and lakhs of payments.
"""
import html
import io
from datetime import date, datetime, timedelta

from ..db import Database
from .teacher_data import TZ, ReportError, mask_phone, parse_period  # noqa: F401


_PAID = """
    FROM payments p
    JOIN plans pl ON pl.id = p.plan_id
    JOIN teachers t ON t.id = pl.teacher_id
    JOIN students st ON st.id = p.student_id
    WHERE p.status = 'paid' AND p.created_at >= datetime(?, 'unixepoch') AND p.created_at < datetime(?, 'unixepoch')
"""
_PCT = "COALESCE(p.platform_percent, t.platform_commission_percent, ?)"


def _where(teacher_id: str | None, q: str = "") -> tuple[str, tuple]:
    sql, args = "", ()
    if teacher_id:
        sql += " AND t.id = ?"
        args += (teacher_id,)
    if q:
        sql += " AND (t.name LIKE ? OR st.name LIKE ? OR substr(st.phone, -4) = ? OR p.razorpay_payment_id = ?)"
        args += (f"%{q}%", f"%{q}%", q[-4:], q)
    return sql, args


def summary(db: Database, start: float, end: float, default_pct: float, teacher_id: str | None = None) -> dict:
    w, a = _where(teacher_id)
    r = db.one(f"""SELECT COUNT(*) AS subs, COALESCE(SUM(p.amount_paise), 0) AS gross,
                   COALESCE(SUM(ROUND(p.amount_paise * {_PCT} / 100.0)), 0) AS dhurina,
                   COUNT(DISTINCT p.student_id) AS students, COUNT(DISTINCT t.id) AS teachers,
                   SUM(CASE WHEN EXISTS (SELECT 1 FROM payments p2 WHERE p2.student_id = p.student_id AND p2.status = 'paid'
                       AND p2.id < p.id) THEN 1 ELSE 0 END) AS renewals
                   {_PAID} {w}""", (default_pct, start, end, *a))
    return {"subscriptions": r["subs"], "renewals": r["renewals"] or 0, "new": r["subs"] - (r["renewals"] or 0),
            "paying_students": r["students"], "selling_teachers": r["teachers"], "gross_paise": int(r["gross"]),
            "dhurina_paise": int(r["dhurina"]), "teachers_paise": int(r["gross"] - r["dhurina"]),
            "teachers_percent": round((r["gross"] - r["dhurina"]) * 100 / r["gross"], 2) if r["gross"] else None,
            "dhurina_percent": round(r["dhurina"] * 100 / r["gross"], 2) if r["gross"] else None}


def by_teacher(db: Database, start: float, end: float, default_pct: float, sort: str = "sales") -> list[dict]:
    """One row per teacher — including teachers with no sales in the period."""
    rows = db.all(f"""
        SELECT t.id, t.name, t.status, COALESCE(t.platform_commission_percent, ?) AS current_pct,
               (SELECT COUNT(*) FROM students s WHERE s.teacher_id = t.id) AS total_students,
               COUNT(p.id) AS subs, COUNT(DISTINCT p.student_id) AS paying,
               COALESCE(SUM(p.amount_paise), 0) AS gross,
               COALESCE(SUM(ROUND(p.amount_paise * COALESCE(p.platform_percent, t.platform_commission_percent, ?) / 100.0)), 0) AS dhurina,
               SUM(CASE WHEN p.id IS NOT NULL AND EXISTS (SELECT 1 FROM payments p2 WHERE p2.student_id = p.student_id
                   AND p2.status = 'paid' AND p2.id < p.id) THEN 1 ELSE 0 END) AS renewals
        FROM teachers t
        LEFT JOIN plans pl ON pl.teacher_id = t.id
        LEFT JOIN payments p ON p.plan_id = pl.id AND p.status = 'paid'
             AND p.created_at >= datetime(?, 'unixepoch') AND p.created_at < datetime(?, 'unixepoch')
        GROUP BY t.id""", (default_pct, default_pct, start, end))
    out = [{"id": r["id"], "name": r["name"], "status": r["status"], "split_teacher": 100 - r["current_pct"],
            "split_dhurina": r["current_pct"], "total_students": r["total_students"], "paying_students": r["paying"],
            "subscriptions": r["subs"], "renewals": r["renewals"] or 0, "new": r["subs"] - (r["renewals"] or 0),
            "gross_paise": int(r["gross"]), "dhurina_paise": int(r["dhurina"]), "teacher_paise": int(r["gross"] - r["dhurina"])}
           for r in rows]
    key = {"sales": lambda x: -x["gross_paise"], "name": lambda x: x["name"].lower(),
           "students": lambda x: -x["paying_students"], "dhurina": lambda x: -x["dhurina_paise"]}.get(sort, lambda x: -x["gross_paise"])
    out.sort(key=key)
    total = sum(x["gross_paise"] for x in out) or 1
    for x in out:
        x["share_of_sales"] = round(x["gross_paise"] * 100 / total, 1)
    return out


def payments(db: Database, start: float, end: float, default_pct: float, teacher_id: str | None = None,
             q: str = "", offset: int = 0, limit: int = 50) -> dict:
    """Which student paid how much, to which teacher — newest first, 50 per page."""
    w, a = _where(teacher_id, q.strip())
    total = db.one(f"SELECT COUNT(*) AS n {_PAID} {w}", (start, end, *a))["n"]
    limit = max(1, min(limit, 500))
    rows = db.all(f"""SELECT datetime(p.created_at, '+330 minutes') AS created_ist, p.razorpay_payment_id, p.amount_paise, {_PCT} AS pct, pl.name AS plan,
                      t.id AS teacher_id, t.name AS teacher, st.id AS student_id, st.name AS student_name, st.phone,
                      EXISTS (SELECT 1 FROM payments p2 WHERE p2.student_id = p.student_id AND p2.status = 'paid' AND p2.id < p.id) AS renewal
                      {_PAID} {w} ORDER BY p.created_at DESC, p.id DESC LIMIT ? OFFSET ?""",
                   (default_pct, start, end, *a, limit, max(offset, 0)))
    items = []
    for r in rows:
        cut = round(r["amount_paise"] * r["pct"] / 100)
        items.append({"date": r["created_ist"][:16], "payment_id": r["razorpay_payment_id"] or "", "teacher_id": r["teacher_id"],
                      "teacher": r["teacher"], "student_id": r["student_id"], "student": r["student_name"] or "Student",
                      "phone": mask_phone(r["phone"]), "plan": r["plan"], "type": "Renewal" if r["renewal"] else "New",
                      "amount_paise": r["amount_paise"], "dhurina_percent": r["pct"], "dhurina_paise": cut,
                      "teacher_percent": round(100 - r["pct"], 2), "teacher_paise": r["amount_paise"] - cut})
    return {"total": total, "items": items}


def monthly_trend(db: Database, start: float, end: float, default_pct: float, teacher_id: str | None = None) -> list[dict]:
    """Month-by-month totals inside the period (Indian months)."""
    w, a = _where(teacher_id)
    rows = db.all(f"""SELECT strftime('%Y-%m', datetime(p.created_at, '+330 minutes')) AS m, COUNT(*) AS subs,
                      SUM(p.amount_paise) AS gross, SUM(ROUND(p.amount_paise * {_PCT} / 100.0)) AS dhurina
                      {_PAID} {w} GROUP BY m ORDER BY m""", (default_pct, start, end, *a))
    found = {r["m"]: r for r in rows}
    out, d = [], datetime.fromtimestamp(start, TZ).date().replace(day=1)
    last = datetime.fromtimestamp(end - 1, TZ).date()
    while d <= last:
        key = d.strftime("%Y-%m")
        r = found.get(key)
        out.append({"month": key, "label": d.strftime("%b %Y"), "subscriptions": r["subs"] if r else 0,
                    "gross_paise": int(r["gross"]) if r else 0, "dhurina_paise": int(r["dhurina"]) if r else 0})
        d = (d + timedelta(days=32)).replace(day=1)
    return out


def full_report(db: Database, date_from: str, date_to: str, default_pct: float, teacher_id: str | None = None,
                sort: str = "sales") -> dict:
    start, end, l1, l2 = parse_period(date_from, date_to)
    teachers = by_teacher(db, start, end, default_pct, sort)
    if teacher_id:
        teachers = [t for t in teachers if t["id"] == teacher_id]
    return {"period_from": l1, "period_to": l2, "date_from": date_from, "date_to": date_to, "teacher_id": teacher_id,
            "generated_on": datetime.now(TZ).strftime("%d %b %Y, %I:%M %p"),
            "summary": summary(db, start, end, default_pct, teacher_id), "by_teacher": teachers,
            "monthly": monthly_trend(db, start, end, default_pct, teacher_id)}


# ---------------------------------------------------------------- export

def _rs(p: int) -> float:
    return round(p / 100, 2)


def export_xlsx(db: Database, rep: dict, default_pct: float) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    head, fill = Font(bold=True, color="FFFFFF"), PatternFill("solid", fgColor="0F766E")
    wb = Workbook()

    def table(ws, cols, rows, money_idx, widths, total=True):
        ws.append(cols)
        for c in ws[ws.max_row]:
            c.font, c.fill, c.alignment = head, fill, Alignment(horizontal="center", wrap_text=True)
        first = ws.max_row + 1
        for r in rows:
            ws.append(r)
        last = ws.max_row
        if total and rows:
            t = ["Total"] + [""] * (len(cols) - 1)
            for i in money_idx:
                col = chr(65 + i)
                t[i] = f"=SUM({col}{first}:{col}{last})"
            ws.append(t)
            for c in ws[ws.max_row]:
                c.font = Font(bold=True)
        for i in money_idx:
            for row in ws.iter_rows(min_row=first, max_row=ws.max_row, min_col=i + 1, max_col=i + 1):
                for c in row:
                    c.number_format = "#,##0.00"
        for i, wdt in enumerate(widths):
            ws.column_dimensions[chr(65 + i)].width = wdt
        ws.freeze_panes = ws.cell(first, 1)

    s = rep["summary"]
    ws = wb.active
    ws.title = "Summary"
    ws.append(["LiveTeach – Dhurina sales report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Period: {rep['period_from']} to {rep['period_to']}"])
    ws.append([f"Generated on: {rep['generated_on']}"])
    ws.append([])
    for k, v in [("Total sales (₹)", _rs(s["gross_paise"])), ("Teachers' earnings (₹)", _rs(s["teachers_paise"])),
                 ("Teachers' share (% of sales)", s["teachers_percent"]), ("Dhurina earnings (₹)", _rs(s["dhurina_paise"])),
                 ("Dhurina share (% of sales)", s["dhurina_percent"]), ("Subscriptions", s["subscriptions"]),
                 ("New", s["new"]), ("Renewals", s["renewals"]), ("Paying students", s["paying_students"]),
                 ("Teachers with sales", s["selling_teachers"])]:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 30, 18
    ws.append([])
    ws.append(["Amounts are before payment-gateway fees."])

    table(wb.create_sheet("By teacher"),
          ["Teacher", "App status", "All students", "Paying students", "Subscriptions", "New", "Renewals",
           "Sales (₹)", "Teacher %", "Teacher earnings (₹)", "Dhurina %", "Dhurina earnings (₹)", "Share of sales %"],
          [[t["name"], t["status"], t["total_students"], t["paying_students"], t["subscriptions"], t["new"], t["renewals"],
            _rs(t["gross_paise"]), t["split_teacher"], _rs(t["teacher_paise"]), t["split_dhurina"], _rs(t["dhurina_paise"]),
            t["share_of_sales"]] for t in rep["by_teacher"]],
          [7, 9, 11], [24, 12, 12, 14, 13, 8, 10, 14, 10, 16, 10, 16, 13])

    start, end, _, _ = parse_period(rep["date_from"], rep["date_to"])
    pays = payments(db, start, end, default_pct, rep.get("teacher_id"), limit=500)
    rows, off = [], 0
    while True:  # all payments, page by page (never one huge query)
        page = payments(db, start, end, default_pct, rep.get("teacher_id"), offset=off, limit=500)["items"]
        rows += [[p["date"], p["payment_id"], p["teacher"], p["student"], p["phone"], p["plan"], p["type"],
                  _rs(p["amount_paise"]), p["teacher_percent"], _rs(p["teacher_paise"]), p["dhurina_percent"], _rs(p["dhurina_paise"])] for p in page]
        off += 500
        if len(page) < 500 or off >= pays["total"]:
            break
    table(wb.create_sheet("Payments"), ["Date & time", "Payment ID", "Teacher", "Student", "Phone", "Plan", "Type",
                                        "Amount (₹)", "Teacher %", "Teacher (₹)", "Dhurina %", "Dhurina (₹)"],
          rows, [7, 9, 11], [17, 22, 20, 14, 14, 10, 9, 12, 10, 12, 10, 12])
    table(wb.create_sheet("Monthly"), ["Month", "Subscriptions", "Sales (₹)", "Teachers (₹)", "Dhurina (₹)"],
          [[m["label"], m["subscriptions"], _rs(m["gross_paise"]), _rs(m["gross_paise"] - m["dhurina_paise"]), _rs(m["dhurina_paise"])]
           for m in rep["monthly"]], [2, 3, 4], [12, 14, 14, 14, 14])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def export_html(rep: dict) -> str:
    e, s = html.escape, rep["summary"]
    money = lambda p: f"₹{_rs(p):,.2f}"  # noqa: E731
    box = lambda k, v: f"<div class=box><span>{k}</span><b>{v}</b></div>"  # noqa: E731
    pc = lambda v: f"{v:g}%" if v is not None else "—"  # noqa: E731
    trs = "".join(f"<tr><td>{e(t['name'])}</td><td class=r>{t['paying_students']}</td>"
                  f"<td class=r>{t['subscriptions']}</td><td class=r>{money(t['gross_paise'])}</td><td class=r>{pc(t['split_teacher'])}</td>"
                  f"<td class=r>{money(t['teacher_paise'])}</td><td class=r>{pc(t['split_dhurina'])}</td><td class=r>{money(t['dhurina_paise'])}</td>"
                  f"<td class=r>{t['share_of_sales']}%</td></tr>" for t in rep["by_teacher"])
    mrs = "".join(f"<tr><td>{e(m['label'])}</td><td class=r>{m['subscriptions']}</td><td class=r>{money(m['gross_paise'])}</td>"
                  f"<td class=r>{money(m['gross_paise'] - m['dhurina_paise'])}</td><td class=r>{money(m['dhurina_paise'])}</td></tr>" for m in rep["monthly"])
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Dhurina sales report</title><style>
@page {{ size: A4; margin: 14mm; }} body {{ font-family: 'Noto Sans', sans-serif; color: #111827; font-size: 10pt; }}
h1 {{ font-size: 17pt; margin: 0 0 4px; }} h2 {{ font-size: 12pt; margin: 18px 0 6px; }} .muted {{ color: #5B6472; }}
.grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 12px 0; }}
.box {{ border: 1px solid #E3E6EB; border-radius: 8px; padding: 8px 10px; }} .box span {{ display: block; color: #5B6472; font-size: 8.5pt; }}
.box b {{ font-size: 12.5pt; }} table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #0F766E; color: #fff; text-align: left; padding: 5px; font-size: 8.5pt; }} td {{ border-bottom: 1px solid #E3E6EB; padding: 4px 5px; }}
.r {{ text-align: right; }}
</style></head><body><h1>LiveTeach — Dhurina sales report</h1>
<b>Period: {e(rep['period_from'])} to {e(rep['period_to'])}</b><div class=muted>Generated on {e(rep['generated_on'])}</div>
<div class=grid>{box('Total sales', money(s['gross_paise']))}{box('Teachers’ earnings · ' + pc(s['teachers_percent']), money(s['teachers_paise']))}{box('Dhurina earnings · ' + pc(s['dhurina_percent']), money(s['dhurina_paise']))}
{box('Subscriptions', f"{s['subscriptions']} ({s['new']} new · {s['renewals']} renewals)")}{box('Paying students', s['paying_students'])}{box('Teachers with sales', s['selling_teachers'])}</div>
<h2>Sales by teacher</h2><table><thead><tr><th>Teacher</th><th class=r>Paying students</th><th class=r>Subs</th>
<th class=r>Sales</th><th class=r>Teacher %</th><th class=r>Teacher earnings</th><th class=r>Dhurina %</th><th class=r>Dhurina earnings</th><th class=r>Share</th></tr></thead><tbody>{trs}</tbody></table>
<h2>Month by month</h2><table><thead><tr><th>Month</th><th class=r>Subscriptions</th><th class=r>Sales</th><th class=r>Teachers</th><th class=r>Dhurina</th></tr></thead><tbody>{mrs}</tbody></table>
<p class=muted>Every payment, student by student, is in the Excel export. Amounts are before payment-gateway fees.</p></body></html>"""
