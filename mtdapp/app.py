"""Thembelani MTD Production app.

Run:  python -m mtdapp          (then open http://localhost:5000)
"""
import csv
import hmac
import io
import json
import os
import re
import secrets
import shutil
import sqlite3
import tempfile
import uuid
from datetime import date, datetime, timedelta

from flask import (Flask, Response, abort, flash, redirect, render_template, request, send_file, session,
                   url_for)
from werkzeug.middleware.proxy_fix import ProxyFix

from . import calc, fields as F, history_import, parser, report
from .db import DB

BASE = os.environ.get("MTD_DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))


def apply_reporting_date(records):
    """Reports uploaded together belong to one reporting day, and the engineering
    report's date is the authoritative reporting date. Returns messages to show."""
    by_report = {}
    for r in records:
        by_report.setdefault(r["report"], []).append(r)
    if any(len(v) > 1 for v in by_report.values()):
        return []          # a multi-day back-fill: every row keeps its own date
    eng = by_report.get(F.ENGINEERING)
    if eng:
        day = eng[0]["date"]
        for r in records:
            if r["date"] != day:
                r["date_note"] = f"file says {r['date']}; set to the engineering report date"
                r["date"] = day
        return []
    dates = sorted({r["date"] for r in records})
    if len(dates) > 1:
        return ["No engineering report in this upload, so there is no authoritative reporting date. "
                "The files carry different dates (" + ", ".join(dates) + "): set the correct date before saving."]
    return []


def _stored_secret(data_dir):
    """A random session key kept in the data folder, so logins survive restarts."""
    path = os.path.join(data_dir, ".secret_key")
    if not os.path.exists(path):
        with open(path, "w") as fh:
            fh.write(secrets.token_hex(32))
    return open(path).read().strip()


def create_app(db_path=None, data_dir=None):
    data_dir = data_dir or BASE
    os.makedirs(data_dir, exist_ok=True)
    app = Flask(__name__)
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)   # behind the host's HTTPS proxy
    app.secret_key = os.environ.get("MTD_SECRET") or _stored_secret(data_dir)
    app.config.update(MAX_CONTENT_LENGTH=50 * 1024 * 1024, PERMANENT_SESSION_LIFETIME=timedelta(days=30),
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                      SESSION_COOKIE_SECURE=os.environ.get("MTD_SECURE_COOKIES") == "1")
    password = os.environ.get("MTD_PASSWORD", "")
    db_file = db_path or os.path.join(data_dir, "mtd.db")
    db = DB(db_file)
    uploads_dir = os.path.join(data_dir, "uploads")
    pending_dir = os.path.join(data_dir, "pending")
    app.db = db

    @app.template_filter("n")
    def n_filter(v, dp=0):
        return calc.fmt(v, dp)

    @app.template_filter("v")
    def value_filter(v):
        """Whole numbers without decimals, otherwise up to 2 decimals."""
        if v is None:
            return "—"
        return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}".rstrip("0")

    @app.template_filter("signed")
    def signed(v, dp=0):
        return "—" if v is None else f"{v:+,.{dp}f}"

    @app.template_filter("dmy")
    def dmy(iso):
        try:
            return datetime.strptime(iso, "%Y-%m-%d").strftime("%d-%b-%Y")
        except (TypeError, ValueError):
            return iso or "—"

    @app.context_processor
    def ctx():
        return dict(REPORTS=F.REPORTS, months=db.months(), today=date.today().isoformat())

    def current_month():
        m = request.values.get("month")
        if m and re.fullmatch(r"\d{4}-\d{2}", m):
            return m
        ms = db.months()
        return ms[0] if ms else date.today().strftime("%Y-%m")

    # ---- login (only when MTD_PASSWORD is set) ------------------------------
    @app.before_request
    def require_login():
        if not password or request.endpoint in ("login", "healthz", "static"):
            return None
        if not session.get("ok"):
            return redirect(url_for("login", next=request.full_path if request.method == "GET" else None))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not password:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            if hmac.compare_digest(request.form.get("password", "").encode(), password.encode()):
                session.clear()
                session.permanent = True
                session["ok"] = True
                nxt = request.args.get("next") or ""
                return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
            flash("Wrong password.", "error")
        return render_template("login.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login") if password else url_for("dashboard"))

    @app.route("/healthz")
    def healthz():
        return "ok"

    @app.context_processor
    def auth_ctx():
        return dict(login_enabled=bool(password))

    # ---- backup / restore ---------------------------------------------------------
    @app.route("/backup")
    def backup():
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        src, dst = sqlite3.connect(db_file), sqlite3.connect(tmp.name)
        with dst:
            src.backup(dst)
        src.close()
        dst.close()
        data = open(tmp.name, "rb").read()
        os.remove(tmp.name)
        return send_file(io.BytesIO(data), as_attachment=True, mimetype="application/octet-stream",
                         download_name=f"mtd-backup-{date.today().isoformat()}.db")

    @app.route("/restore", methods=["POST"])
    def restore():
        f = request.files.get("backup")
        data = f.read() if f else b""
        if not data.startswith(b"SQLite format 3"):
            flash("That file is not an MTD backup (.db).", "error")
            return redirect(url_for("settings"))
        tmp = db_file + ".restore"
        with open(tmp, "wb") as out:
            out.write(data)
        try:
            with sqlite3.connect(tmp) as c:
                c.execute("SELECT count(*) FROM entries").fetchone()
        except sqlite3.Error:
            os.remove(tmp)
            flash("That backup file is damaged.", "error")
            return redirect(url_for("settings"))
        if os.path.exists(db_file):
            shutil.copy(db_file, db_file + f".before-restore-{datetime.now():%Y%m%d-%H%M%S}")
        os.replace(tmp, db_file)
        flash("Backup restored. The previous data was kept as a copy on the server.", "ok")
        return redirect(url_for("dashboard"))

    # ---- dashboard ---------------------------------------------------------
    @app.route("/")
    def dashboard():
        month = current_month()
        as_at = request.args.get("as_at") or None
        d = calc.dashboard(db, month, as_at)
        return render_template("dashboard.html", d=d, month=month, actions=db.actions(),
                               chart=json.dumps(d["trend"] if d else []))

    # ---- upload -------------------------------------------------------------
    @app.route("/upload", methods=["GET", "POST"])
    def upload():
        if request.method == "GET":
            return render_template("upload.html", uploads=db.uploads())
        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            flash("Choose at least one file.", "error")
            return redirect(url_for("upload"))
        default_date = parser.to_date(request.form.get("report_date")) if request.form.get("report_date") else None
        forced = request.form.get("report") or None
        os.makedirs(uploads_dir, exist_ok=True)
        records, messages, stored = [], [], []
        for f in files:
            data = f.read()
            name = os.path.basename(f.filename)
            keep = f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:6]}-{re.sub(r'[^A-Za-z0-9._-]', '_', name)}"
            with open(os.path.join(uploads_dir, keep), "wb") as out:
                out.write(data)
            if history_import.is_consolidated(data):
                log = history_import.import_consolidated(db, data, name)
                db.log_upload(name, keep, "History import: " + "; ".join(log))
                flash(f"{name}: consolidated workbook imported as history — " + "; ".join(log), "ok")
                continue
            try:
                recs, msgs = parser.parse_file(data, name, default_date, forced)
            except Exception as e:  # unreadable file
                messages.append(f"{name}: could not be read ({e})")
                continue
            for r in recs:
                r["date"] = r["date"].isoformat()
                r["file"], r["stored"] = name, keep
            records += recs
            messages += msgs
            stored.append(keep)
        if not records:
            for m in messages:
                flash(m, "error")
            return redirect(url_for("upload"))
        messages += apply_reporting_date(records)
        for r in records:
            r["exists"] = db.day(r["report"], r["date"]) is not None
        os.makedirs(pending_dir, exist_ok=True)
        token = uuid.uuid4().hex
        with open(os.path.join(pending_dir, token + ".json"), "w") as out:
            json.dump(records, out, default=str)
        return render_template("review.html", records=records, messages=messages, token=token)

    @app.route("/upload/confirm", methods=["POST"])
    def upload_confirm():
        token = request.form.get("token", "")
        if not re.fullmatch(r"[0-9a-f]{32}", token):
            abort(400)
        path = os.path.join(pending_dir, token + ".json")
        if not os.path.exists(path):
            flash("This upload has expired — please upload again.", "error")
            return redirect(url_for("upload"))
        with open(path) as fh:
            records = json.load(fh)
        saved, saved_dates = [], []
        for i, r in enumerate(records):
            if request.form.get(f"use_{i}") != "on":
                continue
            d = request.form.get(f"date_{i}") or r["date"]
            if not parser.to_date(d):
                continue
            d = parser.to_date(d).isoformat()
            if any(k.startswith(f"val_{i}_") for k in request.form):     # values as corrected on screen
                r["values"] = {}
                for k in F.all_keys(r["report"]):
                    v = parser.to_number(request.form.get(f"val_{i}_{k}"))
                    if v is not None:
                        r["values"][k] = v
            if f"note_{i}" in request.form:
                r["note"] = request.form.get(f"note_{i}") or None
            db.save_day(r["report"], d, r["values"], source_file=r["file"], note=r.get("note"))
            saved.append(f"{F.REPORTS[r['report']]['title']} {d}")
            saved_dates.append(d)
            db.log_upload(r["file"], r["stored"], f"Saved {F.REPORTS[r['report']]['title']} for {d} "
                                                  f"({len(r['values'])} figures)")
        os.remove(path)
        flash("Saved: " + ", ".join(saved) if saved else "Nothing saved.", "ok" if saved else "error")
        return redirect(url_for("dashboard", month=max(saved_dates)[:7] if saved_dates else None))

    @app.route("/template/<name>.xlsx")
    def template(name):
        if name != "all" and name not in F.REPORTS:
            abort(404)
        data = report.template(None if name == "all" else name)
        fname = "Daily_Input_Template_All.xlsx" if name == "all" else \
            F.REPORTS[name]["title"].replace(" ", "_") + "_Template.xlsx"
        return send_file(io.BytesIO(data), download_name=fname, as_attachment=True,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    # ---- history / edit ------------------------------------------------------
    @app.route("/history")
    def history():
        month = current_month()
        rep = request.args.get("report", F.PRODUCTION)
        if rep not in F.REPORTS:
            abort(404)
        rows = calc.series(db, rep, month)
        if request.args.get("format") == "csv":
            buf = io.StringIO()
            w = csv.writer(buf)
            fl = F.fields(rep)
            w.writerow(["Date"] + [f["label"] for f in fl] + [f["label"] + " MTD" for f in fl if f.get("mtd")] + ["Note"])
            for r in rows:
                w.writerow([r["date"]] + [r["values"].get(f["key"]) for f in fl] +
                           [r["mtd"].get(f["key"]) for f in fl if f.get("mtd")] + [r["note"] or ""])
            return Response(buf.getvalue(), mimetype="text/csv",
                            headers={"Content-Disposition": f"attachment; filename={rep}_{month}.csv"})
        return render_template("history.html", rows=rows, rep=rep, month=month, fields=F.fields(rep))

    @app.route("/day/<rep>", methods=["GET", "POST"])
    @app.route("/day/<rep>/<day>", methods=["GET", "POST"])
    def edit_day(rep, day=None):
        if rep not in F.REPORTS:
            abort(404)
        if request.method == "POST":
            if request.form.get("delete") and day:
                db.delete_day(rep, day)
                flash(f"Deleted {F.REPORTS[rep]['title']} for {day}.", "ok")
                return redirect(url_for("history", report=rep, month=day[:7]))
            new_day = parser.to_date(request.form.get("date"))
            if not new_day:
                flash("Enter a valid date.", "error")
                return redirect(request.url)
            vals = {}
            for k in F.all_keys(rep):
                v = parser.to_number(request.form.get(k))
                if v is not None:
                    vals[k] = v
            if day and day != new_day.isoformat():
                db.delete_day(rep, day)
            db.save_day(rep, new_day.isoformat(), vals, source_file="manual entry",
                        note=request.form.get("note") or None)
            flash(f"Saved {F.REPORTS[rep]['title']} for {new_day.isoformat()}.", "ok")
            return redirect(url_for("history", report=rep, month=new_day.isoformat()[:7]))
        rec = db.day(rep, day) if day else None
        if day and not rec:
            abort(404)
        return render_template("day.html", rep=rep, day=day, rec=rec or {"values": {}}, fields=F.fields(rep))

    # ---- settings & calendar ---------------------------------------------------
    @app.route("/settings", methods=["GET", "POST"])
    def settings():
        month = current_month()
        if request.method == "POST":
            for s in F.SETTINGS:
                v = parser.to_number(request.form.get(s["key"]))
                if v is not None:
                    db.set_setting(month, s["key"], v)
            for s in F.SPILLAGE_SETTINGS:
                v = parser.to_number(request.form.get(s["key"]))
                if v is not None:
                    db.set_setting("global", s["key"], v)
            anchor = parser.to_date(request.form.get("anchor"))
            if anchor:
                if anchor.weekday() != 5:
                    flash("The reference working Saturday must be a Saturday — not changed.", "error")
                else:
                    db.set_setting("global", "working_saturday_anchor", anchor.toordinal())
            flash("Settings saved.", "ok")
            return redirect(url_for("settings", month=month))
        anchor = date.fromordinal(int(db.settings("global", calc.ANCHOR_DEF)["working_saturday_anchor"]))
        return render_template("settings.html", month=month, ms=db.month_settings(month),
                               sp=db.spillage_settings(), anchor=anchor.isoformat(),
                               SETTINGS=F.SETTINGS, SPILL=F.SPILLAGE_SETTINGS)

    @app.route("/calendar", methods=["GET", "POST"])
    def calendar_page():
        month = current_month()
        if request.method == "POST":
            day = request.form["date"]
            if request.form.get("reset"):
                db.clear_calendar(day)
            else:
                db.set_calendar(day, parser.to_number(request.form.get("shifts")),
                                request.form.get("status") or None, request.form.get("note") or None)
            return redirect(url_for("calendar_page", month=month))
        d = calc.dashboard(db, month)
        return render_template("calendar.html", month=month, cal=calc.roster(db, month),
                               as_at=d["as_at"] if d else None, rec=d["recovery"] if d else None)

    # ---- actions -----------------------------------------------------------------
    @app.route("/actions", methods=["GET", "POST"])
    def actions():
        if request.method == "POST":
            aid = request.form.get("id")
            if request.form.get("delete") and aid:
                db.delete_action(int(aid))
            else:
                db.save_action({k: request.form.get(k) for k in
                                ("status", "finding", "action", "owner", "due", "measure")} |
                               {"closed": 1 if request.form.get("closed") else 0}, int(aid) if aid else None)
            return redirect(url_for("actions", all=request.args.get("all")))
        return render_template("actions.html", actions=db.actions(include_closed=bool(request.args.get("all"))))

    # ---- export ---------------------------------------------------------------------
    @app.route("/export")
    def export():
        month = current_month()
        return send_file(io.BytesIO(report.export_month(db, month)),
                         download_name=f"Thembelani_Consolidated_MTD_{month}.xlsx", as_attachment=True,
                         mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    return app


def main():
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    if os.environ.get("HOST") == "0.0.0.0" and not os.environ.get("MTD_PASSWORD"):
        print("Note: no MTD_PASSWORD set - anyone on this network can open the app.")
    host = os.environ.get("HOST", "127.0.0.1")
    print(f"MTD app running on http://{host}:{port}  (data folder: {BASE})")
    app.run(host=host, port=port, debug=False)
