"""Teacher dashboard data that must work at scale: review queue (hundreds of answers), students
(thousands), and the monthly earnings report exported as Excel or PDF."""
import html
import io
import json
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo(os.environ.get("REPORT_TZ", "Asia/Kolkata"))   # months and dates in Indian time

from ..db import Database

# ---------------------------------------------------------------- review queue

def _norm(q: str) -> str:
    """Same question asked by many students → one group ('Rajasthan ki rajdhani?' == 'rajasthan ki rajdhani')."""
    return re.sub(r"[\s\W_]+", " ", q.lower(), flags=re.UNICODE).strip()


def review_page(db: Database, teacher_id: str, offset: int = 0, limit: int = 20, q: str = "",
                origin: str = "", sort: str = "most_asked", status: str = "pending") -> dict:
    """Answers grouped by question. status = pending (waiting), approved or rejected.
    500 waiting answers about 120 distinct questions show as 120 rows, most-asked first, 20 per page."""
    where = {"pending": "h.needs_review = 1", "approved": "h.review_status = 'approved'",
             "rejected": "h.review_status = 'rejected'"}.get(status, "h.needs_review = 1")
    rows = db.all("SELECT h.id, h.question, h.answer, h.origin, h.language, h.created_at, h.sources, h.reviewed_at, "
                  "v.answer AS verified_answer, v.id AS verified_id "
                  "FROM qa_history h JOIN students s ON s.id = h.student_id "
                  "LEFT JOIN verified_answers v ON v.id = h.verified_id "
                  f"WHERE s.teacher_id = ? AND {where} ORDER BY h.id DESC", (teacher_id,))
    groups: dict[str, dict] = {}
    for r in rows:
        if origin and r["origin"] != origin:
            continue
        if q and q.lower() not in (r["question"] + " " + r["answer"]).lower():
            continue
        g = groups.setdefault(_norm(r["question"]), {
            "ids": [], "question": r["question"], "answer": r["verified_answer"] or r["answer"], "origin": r["origin"],
            "language": r["language"], "latest": r["created_at"], "reviewed_at": r["reviewed_at"],
            "verified_id": r["verified_id"],
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
            cur = db.execute("INSERT INTO verified_answers (teacher_id, question, answer, language) VALUES (?, ?, ?, ?)",
                             (teacher_id, rows[0]["question"], answer, rows[0]["language"]))
            db.execute(f"UPDATE qa_history SET needs_review = 0, review_status = 'approved', reviewed_at = CURRENT_TIMESTAMP, "
                       f"verified_id = ? WHERE id IN ({marks})", (cur.lastrowid, *own))
        elif d.get("action") == "reject":
            db.execute(f"UPDATE qa_history SET needs_review = 0, review_status = 'rejected', reviewed_at = CURRENT_TIMESTAMP "
                       f"WHERE id IN ({marks})", tuple(own))
        else:
            continue
        done += len(own)
    return {"updated": done}


def review_undo(db: Database, teacher_id: str, ids: list[int]) -> dict:
    """Mistake? Put approved/rejected answers back to 'Waiting'. An approved answer stops being used at once."""
    ids = [int(i) for i in ids][:1000]
    if not ids:
        return {"restored": 0}
    marks = ",".join("?" * len(ids))
    rows = db.all(f"SELECT h.id, h.verified_id FROM qa_history h JOIN students s ON s.id = h.student_id "
                  f"WHERE s.teacher_id = ? AND h.id IN ({marks}) AND h.review_status IS NOT NULL", (teacher_id, *ids))
    if not rows:
        return {"restored": 0}
    own = [r["id"] for r in rows]
    for vid in {r["verified_id"] for r in rows if r["verified_id"]}:
        db.execute("UPDATE verified_answers SET active = 0, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND teacher_id = ?",
                   (vid, teacher_id))
    m2 = ",".join("?" * len(own))
    db.execute(f"UPDATE qa_history SET needs_review = 1, review_status = NULL, reviewed_at = NULL, verified_id = NULL "
               f"WHERE id IN ({m2})", tuple(own))
    return {"restored": len(own)}


def edit_verified(db: Database, teacher_id: str, verified_id: int, answer: str) -> dict:
    """Fix an approved answer later — every student gets the new version from the next question on."""
    answer = (answer or "").strip()
    if not answer:
        raise ValueError("Answer cannot be empty")
    cur = db.execute("UPDATE verified_answers SET answer = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ? AND teacher_id = ? AND active = 1",
                     (answer, verified_id, teacher_id))
    if cur.rowcount == 0:
        raise KeyError(verified_id)
    return {"updated": True}


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
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    return datetime(y, m, 1, tzinfo=TZ).timestamp(), datetime(ny, nm, 1, tzinfo=TZ).timestamp()


def _fmt(ts: float, pattern: str = "%d %b %Y") -> str:
    return datetime.fromtimestamp(ts, TZ).strftime(pattern)


def _period(month: str, now: float | None = None) -> tuple[str, str]:
    """'01 Nov 2026' → last day of the month, or today if the month is still running."""
    start, end = month_bounds(month)
    last = min(end - 1, now or time.time())
    if last < start:
        last = end - 1
    return _fmt(start), _fmt(last)


def monthly_report(db: Database, teacher_id: str, month: str, default_percent: float = 20,
                   audience: str = "admin") -> dict:
    """Every paid subscription in the month with totals.
    audience='teacher': only the teacher's own share is shown — nothing about Durina's % or amount."""
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
    p_from, p_to = _period(month)
    rep = {"teacher": t["name"] if t else teacher_id, "month": month, "period_from": p_from, "period_to": p_to,
           "generated_on": _fmt(time.time(), "%d %b %Y, %I:%M %p"), "items": items, "summary": {
        "subscriptions": len(items), "new": sum(1 for i in items if i["type"] == "New"),
        "renewals": sum(1 for i in items if i["type"] == "Renewal"), "students": len({r["sid"] for r in rows}),
        "gross_paise": gross, "durina_paise": durina, "teacher_paise": gross - durina}}
    return teacher_view(rep) if audience == "teacher" else rep


def teacher_view(rep: dict) -> dict:
    """Strip everything about the platform's cut: the teacher sees the total, their % and their money."""
    def share(paise_total, paise_teacher):
        return round(paise_teacher * 100 / paise_total, 2) if paise_total else None
    items = [{"date": i["date"], "payment_id": i["payment_id"], "student": i["student"], "plan": i["plan"], "type": i["type"],
              "amount_paise": i["amount_paise"], "your_percent": round(100 - i["durina_percent"], 2),
              "your_paise": i["teacher_paise"]} for i in rep["items"]]
    s = rep["summary"]
    pcts = {i["your_percent"] for i in items}
    return {**{k: rep[k] for k in ("teacher", "month", "period_from", "period_to", "generated_on")}, "audience": "teacher",
            "items": items, "summary": {"subscriptions": s["subscriptions"], "new": s["new"], "renewals": s["renewals"],
            "students": s["students"], "gross_paise": s["gross_paise"], "your_paise": s["teacher_paise"],
            "your_percent": pcts.pop() if len(pcts) == 1 else share(s["gross_paise"], s["teacher_paise"])}}


def _rs(paise: int) -> float:
    return round(paise / 100, 2)


def report_xlsx(rep: dict) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    teacher = rep.get("audience") == "teacher"
    wb = Workbook()
    ws = wb.active
    ws.title = "Summary"
    head = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="0F766E")
    ws.append([f"LiveTeach – {rep['teacher']} – earnings report"])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([f"Period: {rep['period_from']} to {rep['period_to']}"])
    ws.append([f"Generated on: {rep['generated_on']}"])
    ws.append([])
    s = rep["summary"]
    lines = [("Subscriptions", s["subscriptions"]), ("New", s["new"]), ("Renewals", s["renewals"]),
             ("Paying students", s["students"]), ("Total paid by students (₹)", _rs(s["gross_paise"]))]
    if teacher:
        lines += [("Your share (%)", s["your_percent"]), ("Your earnings (₹)", _rs(s["your_paise"]))]
    else:
        lines += [("Durina share (₹)", _rs(s["durina_paise"])), ("Teacher share (₹)", _rs(s["teacher_paise"]))]
    for k, v in lines:
        ws.append([k, v])
        ws.cell(ws.max_row, 1).font = Font(bold=True)
    ws.column_dimensions["A"].width = 32
    ws.column_dimensions["B"].width = 16
    ws.append([])
    ws.append(["Amounts are before payment-gateway fees. Settlement is done by Razorpay."])

    d = wb.create_sheet("Payments")
    if teacher:
        cols = ["Date", "Payment ID", "Student", "Plan", "Type", "Amount (₹)", "Your share %", "Your earnings (₹)"]
        rows = [[i["date"], i["payment_id"], i["student"], i["plan"], i["type"], _rs(i["amount_paise"]),
                 i["your_percent"], _rs(i["your_paise"])] for i in rep["items"]]
        money_cols, sums = ("F", "H"), {"F": 6, "H": 8}
    else:
        cols = ["Date", "Payment ID", "Student", "Plan", "Type", "Amount (₹)", "Durina %", "Durina (₹)", "Teacher (₹)"]
        rows = [[i["date"], i["payment_id"], i["student"], i["plan"], i["type"], _rs(i["amount_paise"]),
                 i["durina_percent"], _rs(i["durina_paise"]), _rs(i["teacher_paise"])] for i in rep["items"]]
        money_cols, sums = ("F", "H", "I"), {"F": 6, "H": 8, "I": 9}
    d.append(cols)
    for c in d[1]:
        c.font, c.fill, c.alignment = head, fill, Alignment(horizontal="center")
    for r in rows:
        d.append(r)
    n = d.max_row
    total = ["Total"] + [""] * (len(cols) - 1)
    for col, idx in sums.items():
        total[idx - 1] = f"=SUM({col}2:{col}{n})"
    d.append(total)
    for c in d[d.max_row]:
        c.font = Font(bold=True)
    for k, col in enumerate("ABCDEFGHI"[:len(cols)]):
        d.column_dimensions[col].width = [12, 22, 16, 12, 10, 13, 13, 16, 13][k]
    for col in money_cols:
        for c in d[col][1:]:
            c.number_format = "#,##0.00"
    d.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def report_html(rep: dict) -> str:
    s, e = rep["summary"], html.escape
    teacher = rep.get("audience") == "teacher"
    money = lambda p: f"₹{_rs(p):,.2f}"  # noqa: E731
    if teacher:
        head = "<th>Date</th><th>Student</th><th>Plan</th><th>Type</th><th class=r>Amount</th><th class=r>Your share</th><th class=r>Your earnings</th>"
        body = "".join(f"<tr><td>{e(i['date'])}</td><td>{e(i['student'])}</td><td>{e(i['plan'])}</td><td>{e(i['type'])}</td>"
                       f"<td class=r>{money(i['amount_paise'])}</td><td class=r>{i['your_percent']:g}%</td><td class=r>{money(i['your_paise'])}</td></tr>"
                       for i in rep["items"])
        cols = 7
        extra = [("Your share", f"{s['your_percent']:g}%" if s["your_percent"] is not None else "—"), ("Your earnings", money(s["your_paise"]))]
    else:
        head = ("<th>Date</th><th>Student</th><th>Plan</th><th>Type</th><th class=r>Amount</th><th class=r>Durina %</th>"
                "<th class=r>Durina</th><th class=r>Teacher</th>")
        body = "".join(f"<tr><td>{e(i['date'])}</td><td>{e(i['student'])}</td><td>{e(i['plan'])}</td><td>{e(i['type'])}</td>"
                       f"<td class=r>{money(i['amount_paise'])}</td><td class=r>{i['durina_percent']:g}%</td>"
                       f"<td class=r>{money(i['durina_paise'])}</td><td class=r>{money(i['teacher_paise'])}</td></tr>" for i in rep["items"])
        cols = 8
        extra = [("Durina share", money(s["durina_paise"])), ("Teacher share", money(s["teacher_paise"]))]
    body = body or f"<tr><td colspan={cols}>No paid subscriptions in this period.</td></tr>"
    box = lambda k, v: f"<div class=box><span>{k}</span><b>{v}</b></div>"  # noqa: E731
    boxes = (box("Subscriptions", s["subscriptions"]) + box("New / Renewals", f"{s['new']} / {s['renewals']}")
             + box("Paying students", s["students"]) + box("Total paid", money(s["gross_paise"])) + "".join(box(k, v) for k, v in extra))
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Report {e(rep['month'])}</title><style>
@page {{ size: A4; margin: 16mm; }} body {{ font-family: 'Noto Sans', sans-serif; color: #111827; font-size: 10.5pt; }}
h1 {{ font-size: 17pt; margin: 0 0 4px; }} .muted {{ color: #5B6472; }} .period {{ font-size: 11.5pt; font-weight: 700; margin-top: 2px; }}
.grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px; margin: 14px 0; }}
.box {{ border: 1px solid #E3E6EB; border-radius: 8px; padding: 8px 10px; }} .box span {{ display: block; color: #5B6472; font-size: 9pt; }}
.box b {{ font-size: 13pt; }} table {{ width: 100%; border-collapse: collapse; }}
th {{ background: #0F766E; color: #fff; text-align: left; padding: 6px; font-size: 9pt; }}
td {{ border-bottom: 1px solid #E3E6EB; padding: 5px 6px; }} .r {{ text-align: right; }}
</style></head><body><h1>{e(rep['teacher'])} — earnings report</h1>
<div class=period>Period: {e(rep['period_from'])} to {e(rep['period_to'])}</div>
<div class=muted>Generated on {e(rep['generated_on'])} · LiveTeach</div>
<div class=grid>{boxes}</div>
<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>
<p class=muted>Amounts are before payment-gateway fees. Settlement is done by Razorpay.</p></body></html>"""
