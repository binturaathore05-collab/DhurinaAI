"""Admin reports across many teachers and payments."""
import io
import time

import pytest
from openpyxl import load_workbook

from app.db import Database
from app.services import accounts, admin_reports


@pytest.fixture
def db(tmp_path):
    d = Database(str(tmp_path / "r.db"))
    for tid, name, pct in [("subhash", "Subhash Sir", 20), ("meena", "Meena Ma'am", 25), ("rakesh", "Rakesh Sir", 30)]:
        d.execute("INSERT INTO teachers (id, name, platform_commission_percent) VALUES (?, ?, ?)", (tid, name, pct))
        d.execute("INSERT INTO plans (id, teacher_id, name, amount_paise, duration_days) VALUES (?, ?, 'Monthly', 50000, 30)", (f"{tid}-m", tid))
    return d


def pay(db, tid, phone, when, pct, n):
    sid = accounts.get_or_create_student(db, tid, phone)
    db.execute("INSERT INTO payments (student_id, plan_id, razorpay_order_id, razorpay_payment_id, amount_paise, platform_percent, status, created_at) "
               "VALUES (?, ?, ?, ?, 50000, ?, 'paid', ?)", (sid, f"{tid}-m", f"o{n}", f"pay_{n}", pct, when))


def test_sales_by_teacher_with_their_own_split(db):
    n = 0
    for i in range(40):           # Subhash: 40 payments in Nov (20%)
        pay(db, "subhash", f"+91900000{i:04d}", "2026-11-05 10:00:00", 20, n := n + 1)
    for i in range(10):           # Meena: 10 in Nov (25%) + same students renew in Dec
        pay(db, "meena", f"+91911111{i:04d}", "2026-11-10 10:00:00", 25, n := n + 1)
        pay(db, "meena", f"+91911111{i:04d}", "2026-12-10 10:00:00", 25, n := n + 1)
    rep = admin_reports.full_report(db, "2026-11-01", "2026-11-30", 20)
    s = rep["summary"]
    assert s["subscriptions"] == 50 and s["gross_paise"] == 50 * 50000 and s["selling_teachers"] == 2
    assert s["durina_paise"] == 40 * 10000 + 10 * 12500 and s["teachers_paise"] == s["gross_paise"] - s["durina_paise"]
    bt = {t["id"]: t for t in rep["by_teacher"]}
    assert [t["id"] for t in rep["by_teacher"]][:2] == ["subhash", "meena"]          # biggest sales first
    assert bt["rakesh"]["gross_paise"] == 0                                            # teachers with no sales still listed
    assert bt["meena"]["split_durina"] == 25 and bt["subhash"]["share_of_sales"] == 80.0
    dec = admin_reports.full_report(db, "2026-12-01", "2026-12-31", 20)
    assert dec["summary"]["renewals"] == 10 and dec["summary"]["new"] == 0
    q = admin_reports.full_report(db, "2026-11-01", "2026-12-31", 20)
    assert [m["subscriptions"] for m in q["monthly"]] == [50, 10] and q["monthly"][0]["label"] == "Nov 2026"
    only = admin_reports.full_report(db, "2026-11-01", "2026-12-31", 20, teacher_id="meena")
    assert only["summary"]["subscriptions"] == 20 and len(only["by_teacher"]) == 1


def test_payments_paged_and_searchable(db):
    for i in range(120):
        pay(db, "subhash", f"+91900000{i:04d}", "2026-11-05 10:00:00", 20, i)
    start, end, _, _ = admin_reports.parse_period("2026-11-01", "2026-11-30")
    page = admin_reports.payments(db, start, end, 20, limit=50)
    assert page["total"] == 120 and len(page["items"]) == 50 and page["items"][0]["teacher"] == "Subhash Sir"
    assert page["items"][0]["phone"].startswith("••••••") and page["items"][0]["durina_paise"] == 10000
    assert len(admin_reports.payments(db, start, end, 20, offset=100, limit=50)["items"]) == 20
    assert admin_reports.payments(db, start, end, 20, q="0007")["total"] == 1          # last 4 digits of phone
    assert admin_reports.payments(db, start, end, 20, q="pay_7")["total"] == 1         # payment id


def test_export_excel_has_all_sheets_and_every_payment(db):
    for i in range(700):          # more than one page of 500 → export must page through all of them
        pay(db, "subhash" if i % 2 else "meena", f"+91900000{i:04d}", "2026-11-05 10:00:00", 20 if i % 2 else 25, i)
    rep = admin_reports.full_report(db, "2026-11-01", "2026-11-30", 20)
    wb = load_workbook(io.BytesIO(admin_reports.export_xlsx(db, rep, 20)))
    assert wb.sheetnames == ["Summary", "By teacher", "Payments", "Monthly"]
    assert wb["Payments"].max_row == 1 + 700 + 1                                      # header + 700 + total
    assert "Period: 01 Nov 2026 to 30 Nov 2026" in wb["Summary"]["A2"].value
    html_text = admin_reports.export_html(rep)
    assert "Sales by teacher" in html_text and "Meena" in html_text


def test_bad_periods():
    with pytest.raises(admin_reports.ReportError):
        admin_reports.parse_period("2026-11-30", "2026-11-01")
    with pytest.raises(admin_reports.ReportError):
        admin_reports.parse_period("nov", "dec")
