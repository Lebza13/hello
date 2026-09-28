"""Read report screenshots/photos of tables (PNG/JPG) into a grid of cells.

The engineering snapshot and the Shaft Car Report arrive as pictures of Excel
tables. We find the table's ruled lines, cut out every cell, read each cell on
its own with Tesseract OCR, and put the text back into rows and columns. The
result is the same kind of grid an Excel sheet gives, so the normal parser
(label/value, "Total" rows) works on it unchanged.

Needs the Tesseract program installed (see README).
"""
import os
import re
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # one thread per tesseract process; we run cells in parallel

IMAGE_EXT = (".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp")
TARGET = 32          # text line height (px) tesseract reads best
DIGITS = "0123456789,.%/-"


class OCRUnavailable(RuntimeError):
    pass


def is_image(data, filename=""):
    return filename.lower().endswith(IMAGE_EXT) or data[:3] == b"\xff\xd8\xff" or data[:8] == b"\x89PNG\r\n\x1a\n"


def _libs():
    try:
        import cv2
        import numpy as np
        import pytesseract
        cmd = os.environ.get("TESSERACT_CMD") or next(
            (p for p in (r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                         r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe") if os.path.exists(p)), None)
        if cmd:
            pytesseract.pytesseract.tesseract_cmd = cmd
        pytesseract.get_tesseract_version()
    except Exception as e:  # missing package or tesseract binary
        raise OCRUnavailable("Reading images needs Tesseract OCR installed — see README "
                             f"('Reading report images'). ({e.__class__.__name__}: {e})")
    return cv2, np, pytesseract


def _cells(cv2, np, img):
    """Bounding boxes (x, y, w, h) of table cells, in original-image pixels."""
    scale = 3 if max(img.shape[:2]) < 2400 else 1
    big = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    gray = cv2.cvtColor(big, cv2.COLOR_BGR2GRAY)
    bw = cv2.adaptiveThreshold(~gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 15, -2)
    h, w = bw.shape
    # Ruled lines are long and thin; letter strokes are short or thick.
    lines = np.zeros_like(bw)
    for k in ((40 * scale, 1), (1, 20 * scale)):
        kern = cv2.getStructuringElement(cv2.MORPH_RECT, k)
        mask = cv2.dilate(cv2.erode(bw, kern), kern)
        n, lab, stats, _ = cv2.connectedComponentsWithStats(mask)
        thick = stats[:, cv2.CC_STAT_HEIGHT] if k[0] > 1 else stats[:, cv2.CC_STAT_WIDTH]
        keep = np.where(thick <= 4 * scale)[0]
        lines |= np.isin(lab, keep[keep > 0]).astype(np.uint8) * 255
    lines = cv2.dilate(lines, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(~lines, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for c in contours:
        x, y, bw_, bh = cv2.boundingRect(c)
        if bw_ > 8 * scale and bh > 8 * scale and not (bw_ > w * 0.95 and bh > h * 0.9):
            boxes.append((x // scale, y // scale, bw_ // scale, bh // scale))
    if not boxes:          # no ruled table: treat the whole picture as one cell
        boxes = [(0, 0, img.shape[1], img.shape[0])]
    return boxes


def _ocr(pt, img, psm, whitelist=None):
    cfg = f"--psm {psm}" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    d = pt.image_to_data(img, config=cfg, output_type=pt.Output.DICT)
    words = [(t, float(c)) for t, c in zip(d["text"], d["conf"]) if t.strip()]
    if not words:
        return "", 0.0
    return " ".join(t for t, _ in words), min(c for _, c in words)


def _read_cell(cv2, np, pt, light, box):
    x, y, w, h = box
    m = 3 if h > 20 else 1
    cell = light[y + m:y + h - m, x + m:x + w - m]
    if cell.size == 0 or min(cell.shape) < 4:
        return ""
    if np.median(cell) < 110:                # light text on a dark fill
        cell = 255 - cell
    _, th = cv2.threshold(cell, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    ink = np.argwhere(th < 128)
    if len(ink) < 12:
        return ""
    (y0, x0), (y1, x1) = ink.min(0), ink.max(0)
    if y1 - y0 < 5 or x1 - x0 < 2:
        return ""                             # a sliver of border, not text
    crop = cell[y0:y1 + 1, x0:x1 + 1]
    # text lines inside the cell, from the rows that contain ink
    runs, cur = [], 0
    for has_ink in (th[y0:y1 + 1, x0:x1 + 1] < 128).any(1):
        if has_ink:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    if cur:
        runs.append(cur)
    runs = [r for r in runs if r >= 3] or [y1 - y0 + 1]
    line_h = sorted(runs)[len(runs) // 2]

    def prepared(target):
        f = target / line_h
        if crop.shape[1] * f < 2:
            return None
        c = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_AREA if f < 1 else cv2.INTER_CUBIC)
        _, c = cv2.threshold(c, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)   # white background
        return cv2.copyMakeBorder(c, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)

    first = prepared(TARGET)
    if first is None:
        return ""
    text, conf = _ocr(pt, first, 7 if len(runs) == 1 else 6)
    if len(runs) == 1 and not re.search(r"[A-Za-z]{2}", text):
        # Looks like a number: read digits only at several sizes and keep the reading
        # at least two of them agree on (tesseract's own confidence is unreliable here).
        votes = {}
        for t in (24, 30, 36, 44):
            im = prepared(t)
            if im is None:
                continue
            num, _ = _ocr(pt, im, 7, DIGITS)
            if re.fullmatch(r"-?[\d ,.%/]*\d[\d ,.%]*", num):
                votes.setdefault(num.replace(" ", ""), []).append(num)
        if votes:
            best = max(votes.values(), key=len)
            if len(best) >= 2:
                return max(best, key=len)
        if re.fullmatch(r"[oO0-9 ,.%]{1,8}", text) and re.search(r"[oO]", text):
            text = text.replace("o", "0").replace("O", "0")
    if conf < 30 or re.fullmatch(r"[\W_]*", text):
        return ""
    return text


def _cluster(values, tol):
    """Map each value to the index of its cluster (values within tol belong together)."""
    idx, out, last = -1, {}, None
    for v in sorted(set(values)):
        if last is None or v - last > tol:
            idx += 1
        out[v] = idx
        last = v
    return out


def image_grid(data):
    cv2, np, pt = _libs()
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("not a readable image")
    # brightness channel: coloured cell fills and Excel's green error markers turn light,
    # black text stays dark
    light = img.max(axis=2)
    boxes = _cells(cv2, np, img)
    with ThreadPoolExecutor(max(1, min(4, os.cpu_count() or 1))) as ex:
        texts = list(ex.map(lambda b: _read_cell(cv2, np, pt, light, b), boxes))
    rows = _cluster([b[1] for b in boxes], 6)
    cols = _cluster([b[0] for b in boxes], 6)
    n_rows, n_cols = max(rows.values()) + 1, max(cols.values()) + 1
    grid = [[None] * n_cols for _ in range(n_rows)]
    for (x, y, _, _), t in zip(boxes, texts):
        if t:
            r, c = rows[y], cols[x]
            grid[r][c] = t if grid[r][c] is None else grid[r][c] + " " + t
    return [row for row in grid if any(v is not None for v in row)]
