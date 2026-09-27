"""Read the daily input spreadsheets.

Two layouts are understood, on any sheet of an .xlsx/.xlsm/.csv file:

1. Label / value  - a cell holding a known label (e.g. "Reef Hoisted") with the
   number in a cell to its right (or directly below). A "Date" label gives the
   report date. This is the layout of the downloadable templates.

2. Table          - a header row containing "Date" and two or more known labels,
   followed by one row per day. Useful for back-filling many days at once.

Each sheet is matched to one of the three reports (production, engineering,
material cars) by counting how many of that report's labels it contains, so a
single workbook with three sheets and three separate files both work.
"""
import csv
import io
import re
from datetime import date, datetime, timedelta

from . import fields as F

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def norm(text):
    """'U/G Trammed (t)' -> 'ugtrammed'"""
    text = re.sub(r"\(.*?\)", "", str(text)).lower()
    return re.sub(r"[^a-z0-9]", "", text)


def label_index(report):
    """normalized label -> storage key, for a report (incl. MTD variants)."""
    idx = {}
    for f in F.fields(report):
        names = [f["label"], f["key"].replace("_", " ")] + f.get("aliases", [])
        for n in names:
            idx.setdefault(norm(n), f["key"])
            if f.get("mtd"):
                for variant in (n + " mtd", "mtd " + n, n + " month to date", n + " cumulative"):
                    idx.setdefault(norm(variant), f["key"] + "_mtd")
    return idx


DATE_KEYS = {norm(a) for a in F.DATE_ALIASES}
NOTE_KEYS = {norm(a) for a in F.NOTE_ALIASES}


def to_number(v):
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace("−", "-").replace(" ", "").replace(",", "")
    m = re.match(r"^([-+]?\d*\.?\d+)(%?)", s)
    if not m or s.lower() in ("", "-", "—", "n/a", "na"):
        return None
    return float(m.group(1))


def to_date(v, default_year=None):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, (int, float)) and 30000 < v < 80000:     # Excel serial date
        return date(1899, 12, 30) + timedelta(days=int(v))
    s = str(v).strip().rstrip("*")
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.search(r"(\d{1,2})[-/. ]([A-Za-z]{3,9})[-/. ,]*(\d{4})?", s)
    if m and m.group(2)[:3].lower() in MONTHS:
        year = int(m.group(3)) if m.group(3) else (default_year or date.today().year)
        return _safe_date(year, MONTHS[m.group(2)[:3].lower()], int(m.group(1)))
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", s)
    if m:  # day/month/year (South African convention)
        return _safe_date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    m = re.search(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    return None


def _safe_date(y, mth, d):
    try:
        return date(y, mth, d)
    except ValueError:
        return None


def read_grids(data, filename):
    """Return [(sheet_name, grid)] where grid is a list of rows of cell values."""
    if filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [(filename, [row for row in csv.reader(io.StringIO(text))])]
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        out.append((ws.title, [list(r) for r in ws.iter_rows(values_only=True)]))
    return out


def _right_or_below(grid, r, c, want):
    row = grid[r]
    for cc in range(c + 1, min(len(row), c + 8)):
        v = row[cc]
        if v is None or str(v).strip() == "":
            continue
        got = want(v)
        if got is not None:
            return got
        break  # stop at the first non-empty cell that isn't the right type
    if r + 1 < len(grid) and c < len(grid[r + 1]):
        return want(grid[r + 1][c])
    return None


def classify(sheet_name, filename, grid, forced=None):
    """Pick the report a sheet belongs to. Returns (report, score)."""
    if forced:
        return forced, 99
    labels = {norm(v) for row in grid for v in row if isinstance(v, str)}
    best, best_score = None, 0
    hint = (sheet_name + " " + filename).lower()
    for rep, spec in F.REPORTS.items():
        score = len(labels & set(label_index(rep)))
        if any(k in hint for k in spec["keywords"]):
            score += 2
        if score > best_score:
            best, best_score = rep, score
    return (best, best_score) if best_score >= 2 else (None, best_score)


def parse_grid(report, grid, default_date=None, filename=""):
    """Extract records [{date, values, note}] from one sheet."""
    idx = label_index(report)
    pct = {f["key"] for f in F.fields(report) if f.get("pct")}
    year = default_date.year if default_date else None

    # --- table layout -----------------------------------------------------
    for r, row in enumerate(grid):
        keys = [norm(v) if isinstance(v, str) else "" for v in row]
        date_cols = [i for i, k in enumerate(keys) if k in DATE_KEYS]
        cols = {i: idx[k] for i, k in enumerate(keys) if k in idx}
        if date_cols and len(cols) >= 2:
            dc = date_cols[0]
            note_col = next((i for i, k in enumerate(keys) if k in NOTE_KEYS), None)
            records = []
            for body in grid[r + 1:]:
                d = to_date(body[dc] if dc < len(body) else None, year)
                if not d:
                    continue
                vals = {}
                for i, key in cols.items():
                    num = to_number(body[i]) if i < len(body) else None
                    if num is not None:
                        vals[key] = _pct(key, num, pct)
                note = body[note_col] if note_col is not None and note_col < len(body) else None
                records.append(dict(date=d, values=vals, note=note))
            if records:
                return records

    # --- label / value layout ----------------------------------------------
    vals, found_date, note = {}, None, None
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if not isinstance(v, str):
                continue
            k = norm(v)
            if k in idx and idx[k] not in vals:
                num = _right_or_below(grid, r, c, to_number)
                if num is not None:
                    vals[idx[k]] = _pct(idx[k], num, pct)
            elif k in DATE_KEYS and not found_date:
                found_date = _right_or_below(grid, r, c, lambda x: to_date(x, year))
            elif k in NOTE_KEYS and not note:
                note = _right_or_below(grid, r, c, lambda x: str(x).strip() or None)
    if not vals:
        return []
    d = found_date or to_date(filename, year) or default_date
    return [dict(date=d, values=vals, note=note)]


def _pct(key, num, pct_keys):
    if key in pct_keys and 0 < abs(num) <= 1.5:
        return round(num * 100, 4)
    return num


def parse_file(data, filename, default_date=None, forced_report=None):
    """Parse an uploaded file. Returns (records, messages).
    Each record: {report, date, values, note, sheet}."""
    records, messages = [], []
    for sheet, grid in read_grids(data, filename):
        report, score = classify(sheet, filename, grid, forced_report)
        if not report:
            messages.append(f"{filename} / {sheet}: not recognised as one of the three reports (skipped)")
            continue
        recs = parse_grid(report, grid, default_date, filename)
        if not recs:
            messages.append(f"{filename} / {sheet}: looked like {F.REPORTS[report]['title']} but no figures found")
        for rec in recs:
            if not rec["date"]:
                messages.append(f"{filename} / {sheet}: no date found - enter a report date and upload again")
                continue
            rec.update(report=report, sheet=sheet)
            records.append(rec)
    return records, messages
