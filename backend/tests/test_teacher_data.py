"""Teacher dashboard at scale: 500 review answers, 1000 students, monthly report export."""
import io
import time

import pytest
from openpyxl import load_workbook

from app.db import Database
from app.services import accounts, teacher_data


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "t.db"))
    d.execute("INSERT INTO teachers (id, name, platform_commission_percent) VALUES ('subhash', 'Subhash Sir', 20)")
    d.execute("INSERT INTO plans (id, teacher_id, name, amount_paise, duration_days) VALUES ('subhash-monthly', 'subhash', 'Monthly', 49900, 30)")
    return d


def test_500_review_answers_grouped_paged_and_bulk_approved(db):
    sid = accounts.get_or_create_student(db, "subhash", "+919876543210")
    for i in range(500):
        q = ["Rajasthan ki rajdhani?", "rajasthan  ki RAJDHANI", "Guru Shikhar kahan hai?"][i % 3] if i < 300 else f"Unique question {i}"
        db.execute("INSERT INTO qa_history (student_id, question, answer, origin, language, needs_review) VALUES (?, ?, 'a', 'general_ai', 'hi', 1)", (sid, q))
    page = teacher_data.review_page(db, "subhash", limit=20)
    assert page["total_answers"] == 500 and page["total"] == 202      # 2 big groups + 200 unique
    assert page["items"][0]["asked"] == 200 and len(page["items"]) == 20   # most-asked first, 20 per page
    assert len(teacher_data.review_page(db, "subhash", offset=200, limit=20)["items"]) == 2
    assert teacher_data.review_page(db, "subhash", q="guru")["total"] == 1
    top = page["items"][0]
    r = teacher_data.review_decide(db, "subhash", [{"ids": top["ids"], "action": "approve", "answer": "Jaipur"},
                                                  {"ids": page["items"][1]["ids"], "action": "reject"}])
    assert r["updated"] == 300
    assert teacher_data.review_page(db, "subhash")["total_answers"] == 200
    assert db.one("SELECT answer FROM verified_answers")["answer"] == "Jaipur"
    assert teacher_data.review_decide(db, "other-teacher", [{"ids": [1], "action": "approve"}])["updated"] == 0  # can't touch others


def test_1000_students_paged_filtered_and_masked(db):
    now = time.time()
    for i in range(1000):
        sid = accounts.get_or_create_student(db, "subhash", f"+9198765{i:05d}")
        if i % 4:  # 750 paid
            ends = now + 40 * 86400 if i % 4 == 1 else now + 86400 if i % 4 == 2 else now - 86400
            db.execute("INSERT INTO subscriptions (student_id, plan_id, starts_at, ends_at) VALUES (?, 'subhash-monthly', ?, ?)", (sid, now - 30 * 86400, ends))
    page = teacher_data.students_page(db, "subhash", limit=25)
    assert page["total"] == 1000 and len(page["items"]) == 25
    assert page["counts"] == {"active": 250, "ending": 250, "ended": 250, "demo": 250}
    assert page["items"][0]["phone"].startswith("••••••") and "98765" not in page["items"][0]["phone"]
    assert teacher_data.students_page(db, "subhash", status="ending")["total"] == 250
    assert teacher_data.students_page(db, "subhash", q="00042")["total"] == 0  # only the last 4 digits are searchable
    assert teacher_data.students_page(db, "subhash", q="0042")["total"] == 1
    assert len(teacher_data.students_page(db, "subhash", offset=975, limit=25)["items"]) == 25


def test_monthly_report_and_excel(db):
    month = time.strftime("%Y-%m")
    s1 = accounts.get_or_create_student(db, "subhash", "+919876500001")
    s2 = accounts.get_or_create_student(db, "subhash", "+919876500002")
    for i, (sid, pct) in enumerate([(s1, 20), (s2, 20), (s1, 25)]):
        db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, razorpay_payment_id, amount_paise, platform_percent, status) "
                   "VALUES (?, 'subhash-monthly', ?, ?, 49900, ?, 'paid')", (sid, f"o{i}", f"pay_{i}", pct))
    rep = teacher_data.monthly_report(db, "subhash", month)
    s = rep["summary"]
    assert s["subscriptions"] == 3 and s["new"] == 2 and s["renewals"] == 1 and s["students"] == 2
    assert s["gross_paise"] == 149700 and s["durina_paise"] == 9980 + 9980 + 12475
    assert s["teacher_paise"] == 149700 - s["durina_paise"]
    wb = load_workbook(io.BytesIO(teacher_data.report_xlsx(rep)))
    assert wb.sheetnames == ["Summary", "Payments"]
    pay = wb["Payments"]
    assert pay["A1"].value == "Date" and pay.max_row == 5 and pay["F5"].value.startswith("=SUM(")
    assert "Subhash Sir" in teacher_data.report_html(rep) and "pay_0" not in teacher_data.report_html(rep)
    assert teacher_data.monthly_report(db, "subhash", "2020-01")["summary"]["subscriptions"] == 0
