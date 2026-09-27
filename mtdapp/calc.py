"""All derived figures: month-to-date totals, recovery maths, spillage model.

The formulas reproduce the consolidated MTD workbook:
  plan to date      = daily call x number of production reports in the month
  projection        = reef hoisted MTD / production reports x planned hoisting days
  equivalent days   = roster shifts remaining after the as-at date / 3
  required rate     = (month plan - MTD hoisted) / equivalent days
"""
import calendar as _cal
from datetime import date, timedelta

from . import fields as F

ANCHOR_DEF = [dict(key="working_saturday_anchor", default=date(2026, 9, 12).toordinal())]


def pct(actual, plan):
    if actual is None or not plan:
        return None
    return actual / plan * 100


def status(p, green=F.GREEN_AT, amber=F.AMBER_AT):
    if p is None:
        return "none"
    return "green" if p >= green else "amber" if p >= amber else "red"


def month_of(d):
    return d[:7]


def month_dates(month):
    y, m = map(int, month.split("-"))
    return [date(y, m, d) for d in range(1, _cal.monthrange(y, m)[1] + 1)]


# ---- running totals --------------------------------------------------------
def series(db, report, month):
    """Rows for a month with daily values and MTD values for accumulating fields.
    A reported MTD figure (key_mtd) wins over the running sum and becomes the
    new base for later days."""
    rows = db.days(report, month)
    mtd_fields = [f["key"] for f in F.fields(report) if f.get("mtd")]
    running = {k: 0.0 for k in mtd_fields}
    seen = set()          # fields reported at least once this month
    out = []
    for r in rows:
        v = r["values"]
        mtd = {}
        for k in mtd_fields:
            rep = v.get(k + "_mtd")
            if rep is not None:
                running[k] = rep
                seen.add(k)
            elif v.get(k) is not None:
                running[k] += v[k]
                seen.add(k)
            mtd[k] = running[k] if k in seen else None
        out.append(dict(date=r["date"], values=v, mtd=mtd, note=r.get("note"), source_file=r.get("source_file")))
    return out


# ---- hoisting calendar ----------------------------------------------------------
def roster(db, month):
    """Default roster: Mon-Fri 3 shifts, Sunday night only, alternate Saturdays
    working (2 shifts) / off, and no Friday night shift before an OFF Saturday.
    Any day can be overridden on the Calendar page."""
    anchor = date.fromordinal(int(db.settings("global", ANCHOR_DEF)["working_saturday_anchor"]))
    overrides = db.calendar_overrides(month)
    out = []
    for d in month_dates(month):
        wd = d.weekday()

        def sat_working(s):
            return ((s - anchor).days // 7) % 2 == 0

        if wd == 5:
            shifts, st, pattern = (2, "WORKING", "Morning, Afternoon") if sat_working(d) else \
                (0, "OFF SATURDAY", "No hoisting shifts")
        elif wd == 6:
            shifts, st, pattern = 1, "NIGHT SHIFT ONLY", "Night"
        elif wd == 4 and not sat_working(d + timedelta(days=1)):
            shifts, st, pattern = 2, "WORKING — NO NIGHT SHIFT", "Morning, Afternoon"
        else:
            shifts, st, pattern = 3, "WORKING", "Morning, Afternoon, Night"
        iso = d.isoformat()
        o = overrides.get(iso)
        note = ""
        if o:
            shifts = o["shifts"] if o["shifts"] is not None else shifts
            st = o["status"] or st
            note = o["note"] or ""
        out.append(dict(date=iso, day=d.strftime("%A"), status=st, pattern=pattern, shifts=shifts,
                        note=note, overridden=bool(o)))
    return out


# ---- dashboard ---------------------------------------------------------------------
def latest_with(rows, keys, as_at):
    for r in reversed(rows):
        if r["date"] <= as_at and any(r["values"].get(k) is not None for k in keys):
            return r
    return None


def dashboard(db, month, as_at=None):
    prod = series(db, F.PRODUCTION, month)
    eng = series(db, F.ENGINEERING, month)
    log = series(db, F.LOGISTICS, month)
    all_dates = [r["date"] for r in prod + eng + log]
    if not as_at:
        as_at = max(all_dates) if all_dates else None
    if not as_at:
        return None
    prod = [r for r in prod if r["date"] <= as_at]
    eng = [r for r in eng if r["date"] <= as_at]
    log = [r for r in log if r["date"] <= as_at]
    s = db.month_settings(month)
    call, wcall = s["daily_call"], s["waste_daily_call"]

    n = len(prod)
    last = prod[-1] if prod else None
    m = last["mtd"] if last else {}
    lv = last["values"] if last else {}
    plan_td = call * n
    wplan_td = wcall * n

    def g(key):
        return m.get(key) if m else None

    mining = []
    for name, a, p, unit in [("Stoping", "stoping_actual", "stoping_plan", "m²"),
                             ("Primary Reef Development", "reef_dev_actual", "reef_dev_plan", "m"),
                             ("Primary Waste Development", "waste_dev_actual", "waste_dev_plan", "m")]:
        act, pl = g(a), g(p)
        p_ = pct(act, pl)
        mining.append(dict(name=name, unit=unit, mtd=act, plan=pl, pct=p_, status=status(p_),
                           deficit=(pl - act) if (pl is not None and act is not None) else None,
                           day_actual=lv.get(a), day_plan=lv.get(p)))

    flow = []
    for name, key, plan in [("U/G Trammed", "trammed", plan_td), ("Reef Hoisted", "reef_hoisted", plan_td),
                            ("Waste Hoisted", "waste_hoisted", wplan_td),
                            ("Concentrator Delivered", "delivered", plan_td)]:
        act = g(key)
        p_ = pct(act, plan)
        flow.append(dict(name=name, key=key, mtd=act, plan=plan, pct=p_, status=status(p_),
                         deficit=(plan - act) if act is not None else None, day=lv.get(key)))

    e = latest_with(eng, [f["key"] for f in F.fields(F.ENGINEERING)], as_at)
    ev = e["values"] if e else {}
    hoisted_day = ev.get("eng_reef_hoisted", lv.get("reef_hoisted"))
    delivered_day = ev.get("eng_delivered", lv.get("delivered"))
    call_ctl = dict(
        call=call,
        hoisted_day=hoisted_day, hoisted_var=None if hoisted_day is None else hoisted_day - call,
        delivered_day=delivered_day, delivered_var=None if delivered_day is None else delivered_day - call,
    )
    call_ctl["hoisted_pct"] = None if hoisted_day is None else (hoisted_day / call - 1) * 100
    call_ctl["delivered_pct"] = None if delivered_day is None else (delivered_day / call - 1) * 100

    stocks = dict(surface=ev.get("surface_stock"), ug=ev.get("ug_stock"))
    stocks["total"] = None if stocks["surface"] is None and stocks["ug"] is None else \
        (stocks["surface"] or 0) + (stocks["ug"] or 0)

    # recovery
    cal = roster(db, month)
    remaining_shifts = sum(c["shifts"] or 0 for c in cal if c["date"] > as_at)
    eq_days = remaining_shifts / 3
    hoisted_mtd = g("reef_hoisted") or 0
    balance = s["monthly_reef_plan"] - hoisted_mtd
    required = balance / eq_days if eq_days else None
    projection = hoisted_mtd / n * s["planned_hoisting_days"] if n else None
    recovery = dict(plan=s["monthly_reef_plan"], mtd=hoisted_mtd, balance=balance,
                    remaining_shifts=remaining_shifts, eq_days=eq_days, required=required,
                    uplift=(required / call - 1) * 100 if required and call else None,
                    projection=projection,
                    shortfall=(s["monthly_reef_plan"] - projection) if projection is not None else None)

    # exceptions: everything below green, worst first
    ex = []
    for f in flow:
        if f["key"] in ("reef_hoisted", "delivered", "trammed") and f["pct"] is not None:
            ex.append(dict(status=f["status"], name=f["name"], pct=f["pct"],
                           detail=f"{f['pct']:.1f}% MTD | deficit {fmt(f['deficit'])} t"))
    for mi in mining:
        if mi["pct"] is not None:
            ex.append(dict(status=mi["status"], name=mi["name"], pct=mi["pct"],
                           detail=f"{mi['pct']:.1f}% MTD | deficit {fmt(mi['deficit'], 1)} {mi['unit']}"))
    ex = sorted([x for x in ex if x["status"] != "green"], key=lambda x: x["pct"])

    return dict(
        month=month, as_at=as_at, settings=s, production_days=n, plan_to_date=plan_td,
        last_production=last, mining=mining, flow=flow, call=call_ctl, engineering=e,
        availability=[(f["label"], ev.get(f["key"])) for f in F.fields(F.ENGINEERING) if f.get("pct")],
        stocks=stocks, spillage=spillage(db, month, eng, as_at), logistics=logistics(log),
        recovery=recovery, exceptions=ex, trend=trend(prod, s), calendar=cal,
    )


def trend(prod, s):
    out = []
    for i, r in enumerate(prod, 1):
        hm = r["mtd"].get("reef_hoisted")
        out.append(dict(date=r["date"], plan=s["daily_call"] * i, hoisted=hm,
                        trammed=r["mtd"].get("trammed"), delivered=r["mtd"].get("delivered"),
                        stoping_plan=r["mtd"].get("stoping_plan"), stoping=r["mtd"].get("stoping_actual"),
                        projection=(hm / i * s["planned_hoisting_days"]) if hm is not None else None))
    return out


def spillage(db, month, eng, as_at):
    p = db.spillage_settings()
    rows, cum = [], 0.0
    for r in eng:
        v = r["values"]
        removed = v["skips"] * p["tonnes_per_skip"] if v.get("skips") is not None else None
        cum += removed or 0
        rows.append(dict(date=r["date"], skips=v.get("skips"), removed=removed, cumulative=cum,
                         underlay=v.get("underlay"), overlay=v.get("overlay")))
    last = next((x for x in reversed(rows) if x["underlay"] is not None or x["overlay"] is not None), None)
    k = p["shaft_area"] * p["density"]
    model = dict(params=p, gross=k * p["datum"], critical=k * (p["datum"] - p["critical_clearance"]),
                 removed=cum, rows=rows)
    if last:
        cl = [x for x in (last["underlay"], last["overlay"]) if x is not None]
        clearance = sum(cl) / len(cl)
        depth = p["datum"] - clearance
        inv = k * depth
        day_no = int(as_at[8:10])
        cal_rate = cum / day_no if day_no else 0
        active = [x for x in rows if (x["skips"] or 0) > 0]
        model.update(
            clearance=clearance, clearance_date=last["date"], depth=depth, inventory=inv,
            pct_critical=inv / model["critical"] * 100, pct_gross=inv / model["gross"] * 100,
            margin=model["critical"] - inv, cal_rate=cal_rate,
            active_rate=(cum / len(active)) if active else None,
            days_to_clear=(inv / cal_rate) if cal_rate else None,
            clearance_status="red" if clearance <= p["critical_clearance"] else
            "amber" if clearance <= p["critical_clearance"] * 3 else "green",
        )
        model["status"] = status(100 - model["pct_critical"], green=40, amber=10)
    return model


def logistics(log):
    if not log:
        return None
    last = log[-1]
    m, v = last["mtd"], last["values"]
    dn, bk = m.get("full_down"), m.get("booked")
    return dict(
        date=last["date"], day=v, mtd=m, rows=log,
        movements_mtd=None if dn is None and m.get("empty_up") is None else (dn or 0) + (m.get("empty_up") or 0),
        movements_day=None if v.get("full_down") is None and v.get("empty_up") is None else
        (v.get("full_down") or 0) + (v.get("empty_up") or 0),
        delivery_pct=pct(dn, bk),
        closing_status="green" if (v.get("closing_ug") or 0) + (v.get("closing_surface") or 0) == 0 else "amber",
    )


def fmt(v, dp=0):
    if v is None:
        return "—"
    return f"{v:,.{dp}f}"
