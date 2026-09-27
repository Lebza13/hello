"""Read the daily input spreadsheets.

Layouts understood, on any sheet of an .xlsx/.xlsm/.csv file or a text PDF:

1. Label / value  - a cell holding a known label (e.g. "Eng Avail", "Actual Reef
   Tonnes") with the number in a cell to its right (or directly below). When a
   daily figure is followed by a second number on the same row (Daily | MTD, as
   on the production report) the second number is stored as the stated MTD.

2. Column totals  - column headers with a "Total" row underneath, as on the
   Shaft Car Report (Booked, Empties Up, Full Cars Down ... and the explosives,
   vent pipe and sling sub-tables).

3. Table          - a header row containing "Date" and two or more known labels,
   followed by one row per day. Useful for back-filling many days at once.

The date comes from a "Date" label (value right, below or left of it), else any
date written in the first rows (e.g. "Daily Report 18 Sept 2026"), else the file
name, else the date typed on the upload form.

Numbers may use South African formatting: "3 513", "56,36%", "13,2".

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
    s = str(v).strip().replace("\u2212", "-")
    s = re.sub(r"[\s\u00a0\u202f]", "", s)          # space thousands separators
    m = re.match(r"^[-+]?[\d.,]*\d", s)
    if not m:
        return None
    num = m.group(0)
    if "," in num and "." in num:                 # the last separator is the decimal one
        num = num.replace(",", "") if num.rfind(".") > num.rfind(",") else num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", "") if re.fullmatch(r"[-+]?\d{1,3}(,\d{3})+", num) else num.replace(",", ".")
    try:
        return float(num)
    except ValueError:
        return None


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


DATE_TEXT = re.compile(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{4}|"
                       r"\d{1,2}[-/. ]+[A-Za-z]{3,9}[-/., ]+\d{4}")


def find_date_text(v):
    """A date written inside text, e.g. 'Thembelani Daily Report 18 Sept 2026'."""
    if isinstance(v, (datetime, date)):
        return to_date(v)
    if not isinstance(v, str):
        return None
    m = DATE_TEXT.search(v)
    return to_date(m.group(0)) if m else None


NUM_WORD = re.compile(r"^[-+\u2212]?\d[\d,.]*%?$")


def words_to_grid(words, gap=3.0):
    """Rebuild table rows from positioned PDF words: [label, number, number, ...].
    Digit groups closer than `gap` points ("25" "149") are one number (25 149)."""
    lines = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]) <= 2.5:
            lines[-1][1].append(w)
        else:
            lines.append((w["top"], [w]))
    grid = []
    for _, ws in lines:
        ws = sorted(ws, key=lambda w: w["x0"])
        label, cells = [], []
        for w in ws:
            t = w["text"]
            prev = cells[-1] if cells else None
            if NUM_WORD.match(t) and label:
                if prev and prev["num"] and w["x0"] - prev["x1"] < gap and re.fullmatch(r"\d{3}([,.]\d+)?%?", t) \
                        and not prev["text"].endswith("%"):
                    prev["text"] += t          # "25" + "149" -> "25149"
                    prev["x1"] = w["x1"]
                else:
                    cells.append(dict(text=t, x1=w["x1"], num=True))
            elif cells:                        # text after the numbers stays one cell
                if prev and not prev["num"]:
                    prev["text"] += " " + t
                    prev["x1"] = w["x1"]
                else:
                    cells.append(dict(text=t, x1=w["x1"], num=False))
            else:
                label.append(t)
        grid.append([" ".join(label)] + [c["text"] for c in cells])
    return grid


def pdf_grid(data):
    import pdfplumber
    grids = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            grids.append((f"page {page.page_number}", words_to_grid(page.extract_words())))
    return grids


def read_grids(data, filename):
    """Return [(sheet_name, grid)] where grid is a list of rows of cell values."""
    from . import ocr
    if ocr.is_image(data, filename):
        return [("image", clean_ocr_grid(ocr.image_grid(data)))]
    if filename.lower().endswith(".pdf") or data[:5] == b"%PDF-":
        return pdf_grid(data)
    if filename.lower().endswith(".csv"):
        text = data.decode("utf-8-sig", errors="replace")
        return [(filename, [row for row in csv.reader(io.StringIO(text))])]
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(data), data_only=True, read_only=True)
    out = []
    for ws in wb.worksheets:
        out.append((ws.title, [list(r) for r in ws.iter_rows(values_only=True)]))
    return out


def _vocabulary():
    """Every label the parser knows, keyed by its normalized form."""
    words = {}
    for rep in F.REPORTS:
        for f in F.fields(rep):
            for n in [f["label"]] + f.get("aliases", []):
                words.setdefault(norm(n), n)
                if f.get("mtd"):
                    words.setdefault(norm(n + " MTD"), n + " MTD")
            for n in f.get("column") or ():
                if n:
                    words.setdefault(norm(n), n)
    for n in F.DATE_ALIASES + F.NOTE_COLUMNS + ["Total"]:
        words.setdefault(norm(n), n)
    return words


NUMBER_TEXT = re.compile(r"[-+]?\d[\d ]*([.,]\d+)?\s*%?")


def clean_ocr_grid(grid):
    """Tidy OCR text: snap near-miss labels to the known wording ('Bogevs Down' ->
    'Bogeys Down') and blank out numbers that were not read cleanly ('2a'), so a
    misread never turns into a wrong figure. Blanked cells show as 'not reported'."""
    import difflib
    vocab = _vocabulary()
    keys = [k for k in vocab if len(k) >= 5]
    out = []
    for row in grid:
        new = []
        for v in row:
            if isinstance(v, str):
                t = v.strip()
                if NUMBER_TEXT.fullmatch(t) or DATE_TEXT.search(t):
                    pass
                elif re.search(r"\d", t) and len(t) <= 8 and not re.search(r"[A-Za-z]{3}", t):
                    t = None                                   # garbled number
                elif norm(t) not in vocab and len(norm(t)) >= 5:
                    m = difflib.get_close_matches(norm(t), keys, n=1, cutoff=0.85)
                    if m:
                        t = vocab[m[0]]
                v = t
            new.append(v)
        out.append(new)
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


def _numbers_right(grid, r, c, limit=2):
    """Numbers following a label on its row (stops at the first text cell)."""
    out = []
    for v in grid[r][c + 1:c + 10]:
        if v is None or str(v).strip() == "":
            continue
        n = to_number(v)
        if n is None:
            break
        out.append(n)
        if len(out) == limit:
            break
    return out


def _left(grid, r, c, want):
    for cc in range(c - 1, -1, -1):
        v = grid[r][cc]
        if v is not None and str(v).strip() != "":
            return want(v)
    return None


def column_totals(report, grid):
    """Values from the 'Total' row under column headers (Shaft Car Report layout).
    Returns (values, warnings). The Total is checked against the level rows above it;
    an unreadable Total is replaced by the sum of the level rows."""
    cells = [(r, c, norm(v)) for r, row in enumerate(grid) for c, v in enumerate(row) if isinstance(v, str)]
    out, warnings = {}, []
    for f in F.fields(report):
        if not f.get("column"):
            continue
        header, group = norm(f["column"][0]), f["column"][1] and norm(f["column"][1])
        cands = [(r, c) for r, c, k in cells if k == header]
        if group:
            grp = [(r, c) for r, c, k in cells if k == group]
            if not grp:
                continue
            gr, gc = grp[0]
            cands = sorted([(r, c) for r, c in cands if r > gr and c >= gc], key=lambda rc: (rc[1] - gc, rc[0]))
        for r, c in cands:
            tr = _total_row(grid, r, c)
            if tr is None:
                continue
            total = to_number(grid[tr][c]) if c < len(grid[tr]) else None
            body = [row[c] if c < len(row) else None for row in grid[r + 1:tr]
                    if any(v is not None and str(v).strip() for v in row[:max(1, c)])]
            nums = [to_number(v) for v in body]
            complete = bool(nums) and all(n is not None for n in nums)
            if total is None and complete:
                total = sum(nums)
                warnings.append(f"{f['label']}: Total unreadable, used the sum of the rows above ({total:g})")
            elif total is not None and complete and abs(sum(nums) - total) > 1e-6:
                warnings.append(f"{f['label']}: Total says {total:g} but the rows above add up to {sum(nums):g}")
            if total is not None:
                out[f["key"]] = total
                break
    return out, warnings


def _total_row(grid, r, c):
    for rr in range(r + 1, min(len(grid), r + 60)):
        if any(isinstance(v, str) and norm(v) in ("total", "totals") for v in grid[rr][:c + 1]):
            return rr
    return None


def column_notes(grid):
    """Text written under 'Remarks' / 'Major Delays' headers."""
    heads = {norm(h) for h in F.NOTE_COLUMNS}
    vocab = _vocabulary()
    notes = []
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if isinstance(v, str) and norm(v) in heads:
                for body in grid[r + 1:r + 40]:
                    t = body[c] if c < len(body) else None
                    if isinstance(t, str) and norm(t) in vocab:
                        break                      # reached the next table's headings
                    if isinstance(t, str) and re.search(r"[A-Za-z]{3}", t):
                        notes.append(t.strip())
    return "; ".join(dict.fromkeys(notes)) or None


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

    # --- column totals + label / value layout --------------------------------
    totals, warnings = column_totals(report, grid)
    vals = {k: _pct(k, v, pct) for k, v in totals.items()}
    mtd_keys = {f["key"] for f in F.fields(report) if f.get("mtd")}
    found_date, note = None, column_notes(grid)
    for r, row in enumerate(grid):
        for c, v in enumerate(row):
            if not isinstance(v, str):
                continue
            k = norm(v)
            if k in idx and idx[k] not in vals:
                nums = _numbers_right(grid, r, c)
                if not nums:
                    below = _right_or_below(grid, r, c, to_number) if c + 1 >= len(row) or all(
                        x is None or str(x).strip() == "" for x in row[c + 1:]) else None
                    nums = [below] if below is not None else []
                if nums:
                    vals[idx[k]] = _pct(idx[k], nums[0], pct)
                    if len(nums) > 1 and idx[k] in mtd_keys and idx[k] + "_mtd" not in vals:
                        vals[idx[k] + "_mtd"] = _pct(idx[k], nums[1], pct)
            elif k in DATE_KEYS and not found_date:
                found_date = _right_or_below(grid, r, c, lambda x: to_date(x, year)) or \
                    _left(grid, r, c, lambda x: to_date(x, year))
            elif k in NOTE_KEYS and not note:
                note = _right_or_below(grid, r, c, lambda x: str(x).strip() or None)
    if not vals:
        return []
    if not found_date:
        found_date = next((d for row in grid[:8] if (d := find_date_text(
            " ".join(str(v) for v in row if v is not None and not isinstance(v, (datetime, date)))) or next(
            (to_date(v) for v in row if isinstance(v, (datetime, date))), None))), None)
    d = found_date or to_date(filename, year) or default_date
    return [dict(date=d, values=vals, note=note, warnings=warnings)]


def _pct(key, num, pct_keys):
    if key in pct_keys and 0 < abs(num) <= 1.5:
        return round(num * 100, 4)
    return num


def parse_file(data, filename, default_date=None, forced_report=None):
    """Parse an uploaded file. Returns (records, messages).
    Each record: {report, date, values, note, sheet}."""
    from . import ocr
    records, messages = [], []
    from_image = ocr.is_image(data, filename)
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
            rec.update(report=report, sheet=sheet, from_image=from_image)
            records.append(rec)
    return records, messages
