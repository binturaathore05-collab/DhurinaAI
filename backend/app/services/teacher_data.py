"""Teacher dashboard data that must work at scale: review queue (hundreds of answers), students
(thousands), and the monthly earnings report exported as Excel or PDF."""
import html
import io
import json
import re
import time

from ..db import Database

# ---------------------------------------------------------------- review queue

def _norm(q: str) -> str:
    """Same question asked by many students → one group ('Rajasthan ki rajdhani?' == 'rajasthan ki rajdhani')."""
    return re.sub(r"[\s\W_]+", " ", q.lower(), flags=re.UNICODE).strip()


def review_page(db: Database, teacher_id: str, offset: int = 0, limit: int = 20, q: str = "",
                origin: str = "", sort: str = "most_asked") -> dict:
    """Answers waiting for the teacher, grouped by question. 500 waiting answers about 120 distinct
    questions show as 120 rows, most-asked first, 20 per page."""
    rows = db.all("SELECT h.id, h.question, h.answer, h.origin, h.language, h.created_at, h.sources "
                  "FROM qa_history h JOIN students s ON s.id = h.student_id "
                  "WHERE s.teacher_id = ? AND h.needs_review = 1 ORDER BY h.id DESC", (teacher_id,))
    groups: dict[str, dict] = {}
    for r in rows:
        if origin and r["origin"] != origin:
            continue
        if q and q.lower() not in (r["question"] + " " + r["answer"]).lower():
            continue
        g = groups.setdefault(_norm(r["question"]), {
            "ids": [], "question": r["question"], "answer": r["answer"], "origin": r["origin"],
            "language": r["language"], "latest": r["created_at"],
            "source": (json.loads(r["sources"] or "[]") or [{"title": r["origin"]}])[0].get("title")})
        g["ids"].append(r["id"])
    items = [{**g, "asked": len(g["ids"])} for g in groups.values()]
    items.sort(key=lambda g: g["latest"], reverse=True)          # newest first …
    if sort == "most_asked":
        items.sort(key=lambda g: g["asked"], reverse=True)       # … then most-asked first (stable)
    limit = max(1, min(limit, 100))
    return {"total_answers": sum(g["asked"] for g in items), "total": len(items),
            "items": items[max(offset, 0):max(offset, 0) + limit]}


def review_decide(db: Database, teacher_id: str, decisions: list[dict]) -> dict:
    """Approve / correct / reject many groups at once: [{ids: [...], action: approve|reject, answer?}]."""
    done = 0
    for d in decisions:
        ids = [int(i) for i in d.get("ids", [])][:1000]
        if not ids:
            continue
        marks = ",".join("?" * len(ids))
        rows = db.all(f"SELECT h.* FROM qa_history h JOIN students s ON s.id = h.student_id "
                      f"WHERE s.teacher_id = ? AND h.id IN ({marks})", (teacher_id, *ids))
        if not rows:
            continue
        own = [r["id"] for r in rows]
        marks = ",".join("?" * len(own))
        if d.get("action") == "approve":
            answer = (d.get("answer") or "").strip() or rows[0]["answer"]
            db.execute("INSERT INTO verified_answers (teacher_id, question, answer, language) VALUES (?, ?, ?, ?)",
                       (teacher_id, rows[0]["question"], answer, rows[0]["language"]))
            db.execute(f"UPDATE qa_history SET needs_review = 0, review_status = 'approved' WHERE id IN ({marks})", tuple(own))
        elif d.get("action") == "reject":
            db.execute(f"UPDATE qa_history SET needs_review = 0, review_status = 'rejected' WHERE id IN ({marks})", tuple(own))
        else:
            continue
        done += len(own)
    return {"updated": done}


# ---------------------------------------------------------------- students

def mask_phone(phone: str) -> str:
    return "•••••• " + (phone or "")[-4:]


def students_page(db: Database, teacher_id: str, offset: int = 0, limit: int = 25, q: str = "",
                  status: str = "", now: float | None = None) -> dict:
    """One page of the teacher's students with what a teacher may see (phone numbers are masked)."""
    now = now or time.time()
    rows = db.all("""
        SELECT s.id, s.name, s.phone, s.level, s.created_at,
               (SELECT MAX(ends_at) FROM subscriptions WHERE student_id = s.id) AS ends_at,
               (SELECT p.name FROM subscriptions su JOIN plans p ON p.id = su.plan_id
                 WHERE su.student_id = s.id ORDER BY su.ends_at DESC LIMIT 1) AS plan,
               (SELECT COUNT(*) FROM qa_history WHERE student_id = s.id) AS questions,
               (SELECT MAX(created_at) FROM qa_history WHERE student_id = s.id) AS last_active,
               (SELECT COUNT(*) FROM saved_notes WHERE student_id = s.id) AS notes,
               (SELECT COALESCE(SUM(amount_paise), 0) FROM payments WHERE student_id = s.id AND status = 'paid') AS paid,
               (SELECT COUNT(*) FROM payments WHERE student_id = s.id AND status = 'paid') AS payments
        FROM students s WHERE s.teacher_id = ? ORDER BY s.id DESC""", (teacher_id,))
    out, counts = [], {"active": 0, "ending": 0, "ended": 0, "demo": 0}
    for r in rows:
        e = r["ends_at"]
        st = "demo" if not e else "ended" if e <= now else "ending" if e - now < 3 * 86400 else "active"
        counts[st] += 1
        if status and st != status:
            continue
        if q and q.lower() not in f"{r['name'] or ''} {r['phone'][-4:]}".lower():
            continue
        out.append({"id": r["id"], "name": r["name"] or "", "phone": mask_phone(r["phone"]), "joined": r["created_at"],
                    "status": st, "plan": r["plan"] or "Demo", "valid_till": e, "last_active": r["last_active"],
                    "questions": r["questions"], "notes": r["notes"], "level": r["level"],
                    "paid_paise": r["paid"], "renewals": max(r["payments"] - 1, 0)})
    limit = max(1, min(limit, 100))
    return {"total": len(out), "counts": counts, "items": out[max(offset, 0):max(offset, 0) + limit]}


# ---------------------------------------------------------------- monthly report

def month_bounds(month: str) -> tuple[float, float]:
    y, m = (int(x) for x in month.split("-"))
    start = time.mktime((y, m, 1, 0, 0, 0, 0, 0, -1))
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return start, time.mktime((ny, nm, 1, 0, 0, 0, 0, 0, -1))


def monthly_report(db: Database, teacher_id: str, month: str, default_percent: float = 20) -> dict:
    """Every paid subscription in the month with the split, plus totals — for the teacher's own accounts."""
    start, end = month_bounds(month)
    t = db.one("SELECT name, platform_commission_percent FROM teachers WHERE id = ?", (teacher_id,))
    rows = db.all("""
        SELECT p.id, p.created_at, p.razorpay_payment_id, p.amount_paise, p.platform_percent, pl.name AS plan,
               st.phone, st.id AS sid,
               (SELECT COUNT(*) FROM payments p2 WHERE p2.student_id = p.student_id AND p2.status = 'paid'
                 AND p2.id < p.id) AS earlier
        FROM payments p JOIN plans pl ON pl.id = p.plan_id JOIN students st ON st.id = p.student_id
        WHERE pl.teacher_id = ? AND p.status = 'paid'
          AND p.created_at >= datetime(?, 'unixepoch') AND p.created_at < datetime(?, 'unixepoch')
        ORDER BY p.created_at""", (teacher_id, start, end))
    items, gross, durina = [], 0, 0
    for r in rows:
        pct = r["platform_percent"]
        pct = (t["platform_commission_percent"] if t and t["platform_commission_percent"] is not None else default_percent) if pct is None else pct
        cut = round(r["amount_paise"] * pct / 100)
        gross, durina = gross + r["amount_paise"], durina + cut
        items.append({"date": r["created_at"][:10], "payment_id": r["razorpay_payment_id"] or "", "student": mask_phone(r["phone"]),
                      "plan": r["plan"], "type": "Renewal" if r["earlier"] else "New",
                      "amount_paise": r["amount_paise"], "durina_percent": pct, "durina_paise": cut,
                      "teacher_paise": r["amount_paise"] - cut})
    return {"teacher": t["name"] if t else teacher_id, "month": month, "items": items, "summary": {
        "subscriptions": len(items), "new": sum(1 for i in items if i["type"] == "New"),
        "renewals": sum(1 for i in items if i["type"] == "Renewal"), "students": len({r["sid"] for r in rows}),
        "gross_paise": gross, "durina_paise": durina, "teacher_paise": gross - durina}}


def _rs(paise: int) -> float:
    return round(paise / 100, 2)


def report_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="0F766E")
    ws.append([f"LiveTeach – {rep['teacher']} – earnings report {rep['month']}"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    s = rep["summary"]
    for k, v in [("Subscriptions", s["subscriptions"]), ("New", s["new"]), ("Renewals", s["renewals"]),
                 ("Paying students", s["students"]), ("Total paid by students (₹)", _rs(s["gross_paise"])),
                 ("Durina share (₹)", _rs(s["durina_paise"])), ("Teacher share (₹)", _rs(s["teacher_paise"]))]:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 30
    ws.column_dimensions["B"].width = 16
    ws.append([])
    ws.append(["Amounts are before payment-gateway fees. Settlement is done by Razorpay."])

    d = wb.create_sheet("Payments")
    cols = ["Date", "Payment ID", "Student", "Plan", "Type", "Amount (₹)", "Durina %", "Durina (₹)", "Teacher (₹)"]
    d.append(cols)
    for c in d[1]:
        c.font, c.fill, c.alignment = head, fill, Alignment(horizontal="center")
    for i in rep["items"]:
        d.append([i["date"], i["payment_id"], i["student"], i["plan"], i["type"], _rs(i["amount_paise"]),
                  i["durina_percent"], _rs(i["durina_paise"]), _rs(i["teacher_paise"])])
    n = d.max_row
    d.append(["Total", "", "", "", "", f"=SUM(F2:F{n})", "", f"=SUM(H2:H{n})", f"=SUM(I2:I{n})"])
    for c in d[d.max_row]:
        c.font = Font(bold=True)
    for col, w in zip("ABCDEFGHI", [12, 22, 16, 12, 10, 13, 10, 13, 13]):
        d.column_dimensions[col].width = w
    for row in d.iter_rows(min_row=2, min_col=6, max_col=9):
        for c in row:
            c.number_format = "#,##0.00"
    d.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_html(rep: dict) -> str:
    s, e = rep["summary"], html.escape
    rows = "".join(f"<tr><td>{e(i['date'])}</td><td>{e(i['student'])}</td><td>{e(i['plan'])}</td><td>{e(i['type'])}</td>"
                   f"<td class=r>₹{_rs(i['amount_paise']):,.2f}</td><td class=r>{i['durina_percent']:g}%</td>"
                   f"<td class=r>₹{_rs(i['durina_paise']):,.2f}</td><td class=r>₹{_rs(i['teacher_paise']):,.2f}</td></tr>"
                   for i in rep["items"]) or "<tr><td colspan=8>No paid subscriptions this month.</td></tr>"
    box = lambda k, v: f"<div class=box><span>{k}</span><b>{v}</b></div>"  # noqa: E731
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Report {e(rep['month'])}</title><style>
@page {{ size: A4; margin: 16mm; }} body {{ font-family: 'Noto Sans', sans-serif; color: #111827; font-size: 10.5pt; }}
h1 {{ font-size: 17pt; margin: 0 0 2px; }} .muted {{ color: #5B6472; }}
.grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 8px; margin: 14px 0; }}
.box {{ border: 1px solid #E3E6EB; border-radius: 8px; padding: 8px 10px; }} .box span {{ display: block; color: #5B6472; font-size: 9pt; }}
.box b {{ font-size: 13pt; }} table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #0F766E; color: #fff; text-align: left; padding: 6px; font-size: 9pt; }}
td {{ border-bottom: 1px solid #E3E6EB; padding: 5px 6px; }} .r {{ text-align: right; }}
</style></head><body><h1>{e(rep['teacher'])} — earnings report</h1><div class=muted>Month {e(rep['month'])} · LiveTeach by Durina Ventures</div>
<div class=grid>{box('Subscriptions', s['subscriptions'])}{box('New / Renewals', f"{s['new']} / {s['renewals']}")}{box('Paying students', s['students'])}
{box('Total paid', f"₹{_rs(s['gross_paise']):,.2f}")}{box('Durina share', f"₹{_rs(s['durina_paise']):,.2f}")}{box('Teacher share', f"₹{_rs(s['teacher_paise']):,.2f}")}</div>
<table><thead><tr><th>Date</th><th>Student</th><th>Plan</th><th>Type</th><th class=r>Amount</th><th class=r>Durina %</th><th class=r>Durina</th><th class=r>Teacher</th></tr></thead>
<tbody>{rows}</tbody></table><p class=muted>Amounts are before payment-gateway fees. Settlement is done by Razorpay.</p></body></html>"""
