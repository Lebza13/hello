"""Definition of the three daily input reports.

Every figure the app stores is listed here once. Each field has:
  key      - internal name (database column)
  label    - what is shown in the app and written into the input templates
  unit     - display unit
  aliases  - other labels that may appear in the source spreadsheets

The upload parser looks for any of the label/aliases in the uploaded workbook
and reads the number next to it (to the right, or directly below). If your
real reports use different wording, add the wording to `aliases` - nothing
else needs to change.

A field with `mtd=True` is a daily figure whose month-to-date value is
accumulated by the app. If the source report also states the MTD value,
the app uses the reported MTD (key `<key>_mtd`) instead of its own running
sum. That keeps the app aligned with "source MTD" figures such as the reset
stoping series.
"""

PRODUCTION = "production"
ENGINEERING = "engineering"
LOGISTICS = "logistics"

REPORTS = {
    PRODUCTION: {
        "title": "Daily Production Report",
        "keywords": ["production", "prod report", "daily report"],
        "fields": [
            dict(key="stoping_plan", label="Stoping Plan", unit="m²", mtd=True,
                 aliases=["daily planned m²", "daily planned m2", "planned m²", "stoping planned"]),
            dict(key="stoping_actual", label="Stoping Actual", unit="m²", mtd=True,
                 aliases=["actual m² blasted", "actual m2 blasted", "stoping", "stoping achieved"]),
            dict(key="reef_dev_plan", label="Primary Reef Development Plan", unit="m", mtd=True,
                 aliases=["plan primary reef", "reef development plan"]),
            dict(key="reef_dev_actual", label="Primary Reef Development Actual", unit="m", mtd=True,
                 aliases=["act primary reef", "actual primary reef", "reef development actual"]),
            dict(key="waste_dev_plan", label="Primary Waste Development Plan", unit="m", mtd=True,
                 aliases=["plan primary waste", "waste development plan"]),
            dict(key="waste_dev_actual", label="Primary Waste Development Actual", unit="m", mtd=True,
                 aliases=["act primary waste", "actual primary waste", "waste development actual"]),
            dict(key="reef_plan", label="Planned Reef Tonnes", unit="t", mtd=True,
                 aliases=["reef hoisted plan", "planned reef tons"]),
            dict(key="reef_hoisted", label="Reef Hoisted", unit="t", mtd=True,
                 aliases=["actual reef tonnes", "actual reef tons", "reef hoisted actual"]),
            dict(key="waste_plan", label="Planned Waste Tonnes", unit="t", mtd=True,
                 aliases=["waste hoisted plan", "planned waste tons"]),
            dict(key="waste_hoisted", label="Waste Hoisted", unit="t", mtd=True,
                 aliases=["actual waste tonnes", "actual waste tons"]),
            dict(key="trammed", label="U/G Trammed", unit="t", mtd=True,
                 aliases=["actual u/g trammed tonnes", "actual ug trammed tonnes", "ug trammed", "tons trammed"]),
            dict(key="delivered", label="Concentrator Delivered", unit="t", mtd=True,
                 aliases=["actual tonnes delivered", "actual tons delivered", "delivered to concentrator"]),
        ],
    },
    ENGINEERING: {
        "title": "Engineering Daily Snapshot",
        "keywords": ["engineering", "snapshot", "eng"],
        "fields": [
            dict(key="engineering_availability", label="Engineering Availability", unit="%", pct=True,
                 aliases=["eng avail", "engineering avail"]),
            dict(key="hoisting_availability", label="Hoisting Availability", unit="%", pct=True,
                 aliases=["hoisting avail", "hoist avail"]),
            dict(key="overall_belt_availability", label="Overall Belt Availability", unit="%", pct=True,
                 aliases=["overall belt avail", "belt availability"]),
            dict(key="surface_belt_availability", label="Surface Belt Availability", unit="%", pct=True,
                 aliases=["sfc belts avail", "sfc belt avail", "surface belts avail"]),
            dict(key="eng_reef_hoisted", label="Hoist Today", unit="t",
                 aliases=["reef hoisted (day)", "hoisted today"]),
            dict(key="eng_hoist_mtd", label="Hoist MTD", unit="t", aliases=["hoisted mtd"]),
            dict(key="eng_delivered", label="Mill Today", unit="t",
                 aliases=["delivered (day)", "delivered today"]),
            dict(key="eng_mill_mtd", label="Mill MTD", unit="t", aliases=["delivered mtd"]),
            dict(key="surface_stock", label="Surface Stock", unit="t", aliases=["surface stocks"]),
            dict(key="ug_stock", label="U/G Stock", unit="t", aliases=["u/g stocks", "ug stock", "underground stock"]),
            dict(key="underlay", label="Underlay", unit="m", aliases=["underlay (meter)", "u/l"]),
            dict(key="overlay", label="Overlay", unit="m", aliases=["overlay (meter)", "o/l"]),
            dict(key="skips", label="Spillage Skips", unit="skips", aliases=["skips"]),
        ],
    },
    LOGISTICS: {
        "title": "Material Car Report",
        "keywords": ["material car", "car report", "logistics"],
        # `column` = (column header, group header above it): the value is read from the
        # "Total" row under that column, as on the Thembelani Shaft Car Report.
        "fields": [
            dict(key="booked", label="Shaft Report Booked", unit="cars", mtd=True, column=("booked", None),
                 aliases=["cars booked"]),
            dict(key="full_down", label="Full Cars Down", unit="cars", mtd=True, column=("full cars down", None),
                 aliases=["number of material cars that went down", "cars down"]),
            dict(key="empty_up", label="Empty Cars Up", unit="cars", mtd=True, column=("empties up", None),
                 aliases=["number of material cars that went up", "cars up"]),
            dict(key="closing_ug", label="Closing Left U/G", unit="cars", column=("empties left underground", None),
                 aliases=["number of cars left underground", "left ug", "left u/g"]),
            dict(key="closing_surface", label="Closing Left Surface", unit="cars",
                 column=("full cars left on surface", None),
                 aliases=["number of cars left on surface", "left surface"]),
            dict(key="cars_not_down", label="Total Cars not Down", unit="cars", column=("total cars not down", None),
                 aliases=[]),
            dict(key="explosives_down", label="Explosives Down", unit="cars", mtd=True,
                 column=("down", "explosives cars"),
                 aliases=["number of explosive cars that went down"]),
            dict(key="vent_pipes_down", label="Vent Pipes Down", unit="pipes", mtd=True, column=("down", "vent pipes"),
                 aliases=[]),
            dict(key="bogeys_slung", label="Bogeys Slung", unit="bogeys", mtd=True, column=("bogeys down", None),
                 aliases=["number of bogeys slung"]),
        ],
    },
}

DATE_ALIASES = ["date", "report date", "production date", "reporting date", "material car report date",
                "snapshot date", "engineering date"]
NOTE_ALIASES = ["note", "notes", "comment", "comments"]
# Columns whose text is collected into the day's note (car report remarks / delays).
NOTE_COLUMNS = ["remarks", "major delays"]


def fields(report):
    return REPORTS[report]["fields"]


def field_map(report):
    return {f["key"]: f for f in fields(report)}


def all_keys(report):
    """Every storable key for a report, including reported-MTD companions."""
    keys = []
    for f in fields(report):
        keys.append(f["key"])
        if f.get("mtd"):
            keys.append(f["key"] + "_mtd")
    return keys


# Month settings with their defaults (values from the September 2026 workbook).
SETTINGS = [
    dict(key="monthly_reef_plan", label="Monthly reef hoisting plan", unit="t", default=125232),
    dict(key="daily_call", label="Daily call (reef)", unit="t/day", default=5218),
    dict(key="waste_daily_call", label="Daily call (waste hoisted)", unit="t/day", default=569.5),
    dict(key="planned_hoisting_days", label="Planned hoisting days", unit="days", default=24),
]

# Shaft-bottom spillage model (global, not per month).
SPILLAGE_SETTINGS = [
    dict(key="shaft_area", label="Shaft cross-sectional area", unit="m²", default=49.3),
    dict(key="density", label="Spillage density", unit="t/m³", default=2.2),
    dict(key="datum", label="Loading box datum to spillage chute", unit="m", default=32.004),
    dict(key="critical_clearance", label="Critical clearance (first bunton)", unit="m", default=4.6),
    dict(key="tonnes_per_skip", label="Tonnes per spillage skip", unit="t", default=0.3),
]

# Status thresholds (% of plan).
GREEN_AT = 95.0
AMBER_AT = 85.0
