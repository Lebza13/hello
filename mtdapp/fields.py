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
        "keywords": ["production"],
        "fields": [
            dict(key="stoping_plan", label="Stoping Plan", unit="m²", mtd=True,
                 aliases=["stoping planned", "stope plan"]),
            dict(key="stoping_actual", label="Stoping Actual", unit="m²", mtd=True,
                 aliases=["stoping", "stoping achieved", "stope actual"]),
            dict(key="reef_dev_plan", label="Primary Reef Development Plan", unit="m", mtd=True,
                 aliases=["reef development plan", "reef dev plan"]),
            dict(key="reef_dev_actual", label="Primary Reef Development Actual", unit="m", mtd=True,
                 aliases=["reef development actual", "reef dev actual", "primary reef development"]),
            dict(key="waste_dev_plan", label="Primary Waste Development Plan", unit="m", mtd=True,
                 aliases=["waste development plan", "waste dev plan"]),
            dict(key="waste_dev_actual", label="Primary Waste Development Actual", unit="m", mtd=True,
                 aliases=["waste development actual", "waste dev actual", "primary waste development"]),
            dict(key="trammed", label="U/G Trammed", unit="t", mtd=True,
                 aliases=["ug trammed", "underground trammed", "trammed", "tons trammed"]),
            dict(key="reef_hoisted", label="Reef Hoisted", unit="t", mtd=True,
                 aliases=["reef hoisted actual", "reef hoist", "ore hoisted"]),
            dict(key="waste_hoisted", label="Waste Hoisted", unit="t", mtd=True,
                 aliases=["waste hoist"]),
            dict(key="delivered", label="Concentrator Delivered", unit="t", mtd=True,
                 aliases=["delivered", "delivered to concentrator", "concentrator delivery"]),
        ],
    },
    ENGINEERING: {
        "title": "Engineering Daily Snapshot",
        "keywords": ["engineering", "snapshot"],
        "fields": [
            dict(key="engineering_availability", label="Engineering Availability", unit="%", pct=True, aliases=[]),
            dict(key="hoisting_availability", label="Hoisting Availability", unit="%", pct=True,
                 aliases=["hoist availability"]),
            dict(key="overall_belt_availability", label="Overall Belt Availability", unit="%", pct=True,
                 aliases=["belt availability"]),
            dict(key="surface_belt_availability", label="Surface Belt Availability", unit="%", pct=True, aliases=[]),
            dict(key="eng_reef_hoisted", label="Reef Hoisted (day)", unit="t",
                 aliases=["reef hoisted today", "reef hoisted day", "daily reef hoisted"]),
            dict(key="eng_delivered", label="Delivered (day)", unit="t",
                 aliases=["delivered today", "delivered day", "daily delivered"]),
            dict(key="surface_stock", label="Surface Stock", unit="t", aliases=["surface stockpile"]),
            dict(key="ug_stock", label="U/G Stock", unit="t", aliases=["ug stock", "underground stock"]),
            dict(key="underlay", label="Underlay", unit="m", aliases=["underlay clearance", "u/l"]),
            dict(key="overlay", label="Overlay", unit="m", aliases=["overlay clearance", "o/l"]),
            dict(key="skips", label="Spillage Skips", unit="skips", aliases=["skips", "spillage skips removed"]),
        ],
    },
    LOGISTICS: {
        "title": "Material Car Report",
        "keywords": ["material car", "car report", "logistics"],
        "fields": [
            dict(key="booked", label="Shaft Report Booked", unit="cars", mtd=True,
                 aliases=["booked", "cars booked", "shaft-report booked"]),
            dict(key="full_down", label="Full Cars Down", unit="cars", mtd=True,
                 aliases=["cars down", "full down", "full material cars down"]),
            dict(key="empty_up", label="Empty Cars Up", unit="cars", mtd=True,
                 aliases=["cars up", "empty up", "empties up"]),
            dict(key="closing_ug", label="Closing Left U/G", unit="cars",
                 aliases=["left ug", "left u/g", "closing ug", "closing u/g", "left underground", "station empties"]),
            dict(key="closing_surface", label="Closing Left Surface", unit="cars",
                 aliases=["left surface", "closing surface", "surface backlog"]),
            dict(key="explosives_down", label="Explosives Down", unit="cars", mtd=True, aliases=["explosives"]),
            dict(key="vent_pipes_down", label="Vent Pipes Down", unit="pipes", mtd=True, aliases=["vent pipes"]),
            dict(key="bogeys_slung", label="Bogeys Slung", unit="bogeys", mtd=True, aliases=["bogeys"]),
        ],
    },
}

DATE_ALIASES = ["date", "report date", "production date", "reporting date", "material car report date",
                "snapshot date", "engineering date"]
NOTE_ALIASES = ["note", "notes", "comment", "comments", "remarks"]


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
