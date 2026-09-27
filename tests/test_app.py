import io
import os
import re
from datetime import date

import openpyxl
import pytest

from mtdapp import calc, fields as F, parser, report
from mtdapp.app import create_app
from mtdapp.db import DB


def filled_template(day, values_by_report):
    """Fill the downloadable 'all reports' template like a user would."""
    wb = openpyxl.load_workbook(io.BytesIO(report.template()))
    for ws in wb.worksheets:
        rep = next(k for k, r in F.REPORTS.items() if r["title"][:31] == ws.title)
        ws["B3"] = day
        labels = {f["label"]: f["key"] for f in F.fields(rep)}
        labels.update({f["label"] + " MTD": f["key"] + "_mtd" for f in F.fields(rep) if f.get("mtd")})
        for row in ws.iter_rows(min_row=7):
            key = labels.get(row[0].value)
            if key and key in values_by_report.get(rep, {}):
                row[1].value = values_by_report[rep][key]
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


SAMPLE = {
    F.PRODUCTION: dict(stoping_plan=1093, stoping_actual=1525, reef_dev_plan=9.6, reef_dev_actual=12.9,
                       waste_dev_plan=17.4, waste_dev_actual=26.4, trammed=7080, reef_hoisted=6385,
                       waste_hoisted=697, delivered=6510),
    F.ENGINEERING: dict(engineering_availability=0.8868, hoisting_availability=88.68, overall_belt_availability=1,
                        surface_belt_availability=100, eng_reef_hoisted=2298, eng_delivered=3843,
                        surface_stock=1123, ug_stock=1300, underlay=12.5, overlay=12.4, skips=0),
    F.LOGISTICS: dict(booked=44, full_down=41, empty_up=54, closing_ug=0, closing_surface=0,
                      explosives_down=0, vent_pipes_down=12),
}


def test_template_round_trip_classifies_and_reads_all_three_sheets():
    data = filled_template(date(2026, 9, 24), SAMPLE)
    recs, msgs = parser.parse_file(data, "daily.xlsx")
    assert not msgs
    by = {r["report"]: r for r in recs}
    assert set(by) == set(F.REPORTS)
    assert all(r["date"] == date(2026, 9, 24) for r in recs)
    assert by[F.PRODUCTION]["values"]["reef_hoisted"] == 6385
    assert by[F.ENGINEERING]["values"]["engineering_availability"] == pytest.approx(88.68)  # fraction -> %
    assert by[F.ENGINEERING]["values"]["overall_belt_availability"] == 100
    assert by[F.LOGISTICS]["values"]["vent_pipes_down"] == 12
    assert "bogeys_slung" not in by[F.LOGISTICS]["values"]  # blank stays "not reported"


def test_label_value_sheet_with_other_wording_and_units_in_text():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Material Car Report"
    ws.append(["Material Car Report Date", "24-Sep-2026"])
    ws.append(["Cars Down", "41"])
    ws.append(["Cars Up", 54])
    ws.append(["Left U/G", 0])
    ws.append(["Left Surface", "0 cars"])
    buf = io.BytesIO()
    wb.save(buf)
    recs, _ = parser.parse_file(buf.getvalue(), "cars.xlsx")
    assert recs[0]["report"] == F.LOGISTICS
    assert recs[0]["date"] == date(2026, 9, 24)
    assert recs[0]["values"] == {"full_down": 41, "empty_up": 54, "closing_ug": 0, "closing_surface": 0}


def test_table_layout_gives_one_record_per_row_and_date_from_filename():
    csv_data = b"Date,Reef Hoisted,U/G Trammed,Concentrator Delivered\n01-Sep-2026,2987,3826,3826\n02-Sep-2026,3946,4146,3837\n"
    recs, _ = parser.parse_file(csv_data, "production_backfill.csv")
    assert [r["date"] for r in recs] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert recs[1]["values"]["reef_hoisted"] == 3946
    assert parser.to_date("Daily_Production_2026-09-23.xlsx") == date(2026, 9, 23)


def test_mtd_accumulates_and_reported_mtd_wins():
    db = DB(":memory:")
    db.save_day(F.PRODUCTION, "2026-09-01", {"reef_hoisted": 100, "stoping_actual": 50})
    db.save_day(F.PRODUCTION, "2026-09-02", {"reef_hoisted": 200, "stoping_actual_mtd": 10})  # series reset
    db.save_day(F.PRODUCTION, "2026-09-03", {"reef_hoisted": 300, "stoping_actual": 5})
    db.save_day(F.PRODUCTION, "2026-10-01", {"reef_hoisted": 7})
    rows = calc.series(db, F.PRODUCTION, "2026-09")
    assert [r["mtd"]["reef_hoisted"] for r in rows] == [100, 300, 600]
    assert [r["mtd"]["stoping_actual"] for r in rows] == [50, 10, 15]
    assert rows[-1]["mtd"]["delivered"] is None
    assert calc.series(db, F.PRODUCTION, "2026-10")[0]["mtd"]["reef_hoisted"] == 7


def test_recovery_matches_workbook_formulas():
    db = DB(":memory:")
    # 19 production reports whose MTD ends at 81,872 t, as at 24 Sep 2026
    for i, d in enumerate([1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12, 14, 15, 16, 17, 18, 21, 22, 24]):
        db.save_day(F.PRODUCTION, f"2026-09-{d:02d}", {"reef_hoisted": 4000} if i < 18 else {"reef_hoisted_mtd": 81872})
    db.save_day(F.ENGINEERING, "2026-09-24", {"eng_reef_hoisted": 2298, "underlay": 12.5, "overlay": 12.4})
    db.set_calendar("2026-09-24", 0, "PUBLIC HOLIDAY", None)
    d = calc.dashboard(db, "2026-09")
    r = d["recovery"]
    assert d["plan_to_date"] == 5218 * 19
    assert r["remaining_shifts"] == 15 and r["eq_days"] == 5
    assert r["required"] == pytest.approx(8672)
    assert r["projection"] == pytest.approx(103417, abs=1)
    assert d["call"]["hoisted_var"] == -2920
    assert d["spillage"]["inventory"] == pytest.approx(2120.8, abs=0.1)
    assert d["exceptions"][0]["name"] == "Reef Hoisted" and d["exceptions"][0]["status"] == "red"


def test_default_roster_september_2026():
    db = DB(":memory:")
    cal = {c["date"]: c for c in calc.roster(db, "2026-09")}
    assert cal["2026-09-04"]["shifts"] == 2          # Friday before OFF Saturday
    assert cal["2026-09-05"]["shifts"] == 0          # OFF Saturday
    assert cal["2026-09-11"]["shifts"] == 3          # Friday before working Saturday
    assert cal["2026-09-12"]["shifts"] == 2          # working Saturday
    assert cal["2026-09-13"]["shifts"] == 1          # Sunday night shift
    assert sum(c["shifts"] for d, c in cal.items() if d > "2026-09-24") == 15


@pytest.fixture
def client(tmp_path):
    app = create_app(data_dir=str(tmp_path))
    app.testing = True
    return app.test_client()


def test_upload_review_confirm_dashboard_export(client):
    data = filled_template(date(2026, 9, 24), SAMPLE)
    r = client.post("/upload", data={"files": (io.BytesIO(data), "daily.xlsx")}, content_type="multipart/form-data")
    assert r.status_code == 200 and b"Check the figures" in r.data
    token = re.search(rb'name="token" value="([0-9a-f]+)"', r.data).group(1).decode()
    form = {"token": token}
    for i in range(3):
        form[f"use_{i}"] = "on"
    r = client.post("/upload/confirm", data=form)
    assert r.status_code == 302
    r = client.get("/?month=2026-09")
    assert r.status_code == 200
    assert b"6,385 t" in r.data and b"-2,920 t" in r.data
    for page in ("/history?report=engineering&month=2026-09", "/calendar?month=2026-09", "/actions",
                 "/settings?month=2026-09", "/upload", "/day/production/2026-09-24", "/day/logistics"):
        assert client.get(page).status_code == 200, page
    x = client.get("/export?month=2026-09")
    wb = openpyxl.load_workbook(io.BytesIO(x.data))
    assert "MTD Dashboard" in wb.sheetnames and "Hoisting Calendar" in wb.sheetnames
    csv_r = client.get("/history?report=production&month=2026-09&format=csv")
    assert b"6385" in csv_r.data


def test_manual_edit_and_delete(client):
    r = client.post("/day/logistics", data={"date": "2026-09-25", "booked": "50", "full_down": "", "note": "hand"})
    assert r.status_code == 302
    db = client.application.db
    assert db.day(F.LOGISTICS, "2026-09-25")["values"] == {"booked": 50}
    client.post("/day/logistics/2026-09-25", data={"delete": "1"})
    assert db.day(F.LOGISTICS, "2026-09-25") is None


SAMPLE_WORKBOOK = os.environ.get("MTD_SAMPLE_WORKBOOK")


@pytest.mark.skipif(not SAMPLE_WORKBOOK, reason="set MTD_SAMPLE_WORKBOOK to the old consolidated workbook")
def test_history_import_reproduces_consolidated_workbook():
    from mtdapp import history_import
    db = DB(":memory:")
    history_import.import_consolidated(db, open(SAMPLE_WORKBOOK, "rb").read())
    d = calc.dashboard(db, "2026-09")
    assert d["as_at"] == "2026-09-24"
    flow = {f["key"]: f for f in d["flow"]}
    assert round(flow["reef_hoisted"]["pct"], 1) == 82.6
    assert round(flow["delivered"]["pct"], 1) == 84.1
    assert [round(m["pct"], 1) for m in d["mining"]] == [90.8, 98.6, 83.3]
    assert d["recovery"]["required"] == pytest.approx(8672)
    assert round(d["recovery"]["projection"]) == 103417
    assert d["logistics"]["mtd"]["full_down"] == 994 and d["logistics"]["mtd"]["empty_up"] == 1198
