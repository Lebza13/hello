# Thembelani MTD Production app

A small web app that replaces the consolidated MTD production spreadsheet.
Each day you upload the three daily reports and the app:

* reads the figures and shows them to you before saving,
* keeps every day in a local database (`data/mtd.db`), so history builds up month after month,
* recalculates the month-to-date dashboard (mining, daily call, material flow, recovery,
  engineering, spillage, logistics, exceptions),
* lets you download a consolidated Excel workbook for any month.

## Start it

Needs Python 3.10 or newer, and **Tesseract OCR** for reading the report pictures:

* Windows: install from https://github.com/UB-Mannheim/tesseract/wiki (default folder is found automatically;
  otherwise set `TESSERACT_CMD` to the full path of `tesseract.exe`)
* Ubuntu/Debian: `sudo apt install tesseract-ocr`

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt        # Windows: .venv\Scripts\pip install -r requirements.txt
.venv/bin/python -m mtdapp                       # Windows: .venv\Scripts\python -m mtdapp
```

Then open http://localhost:5000. To let other PCs on the network use it, start it with
`HOST=0.0.0.0` (and optionally `PORT=8080`). The data folder can be moved with
`MTD_DATA_DIR=/path/to/folder`. Back up that folder to back up all history.

The app needs no internet connection.

## Daily use

1. **Upload daily reports**: select the three reports together: the Daily Production Report (PDF),
   the engineering snapshot (picture) and the Shaft Car Report (picture).
2. Reports uploaded together are one reporting day. **The engineering report's date is the reporting
   date** for all of them (the car report often carries a different date).
3. Check the figures on the review screen. Every figure can be corrected there. Figures read from
   pictures are marked, so compare them with the picture. Press **Save to history**.
   Uploading the same date again replaces it.
4. The **Dashboard** now shows the new position. **Download consolidated Excel** gives the
   workbook for distribution.

Other pages:

| Page | What it is for |
|---|---|
| History | Every saved day per report, with MTD columns, edit or delete a day, CSV download |
| Hoisting calendar | Shifts per day (default roster rules), override public holidays or extra shifts |
| Actions | Management actions list (status, owner, due date, closed) |
| Settings | Monthly plan, daily call, planned hoisting days, roster anchor Saturday, spillage model |

### Loading existing history

Upload the old consolidated workbook (`Thembelani_Consolidated_MTD_Production_Report_*.xlsx`)
once on the Upload page. The app recognises it and imports the trend, spillage, material car,
calendar and management action history.

## How the input files are read

| Report | Arrives as | What is read |
|---|---|---|
| Daily Production Report | PDF | Stoping, primary reef/waste development, planned & actual reef tonnes, waste tonnes, U/G trammed, delivered to concentrator: each **Daily and MTD** |
| Engineering snapshot | Picture (JPG/PNG) | **Reporting date**, Eng/Hoisting/Belt availabilities, Hoist Today/MTD, Mill Today/MTD, surface & U/G stocks, underlay, overlay, skips |
| Shaft Car Report | Picture (JPG/PNG) | The **Total** rows: booked, empties up, empties left underground, full cars down, full cars left on surface; explosives down, vent pipes down, bogeys slung; remarks and major delays become the day's note |

The Shaft Car Report is the authority for all car figures. The car numbers printed on the
production PDF are ignored, and figures from an uploaded car report replace any imported history
for that day.

The same reports as Excel files work too.

**Pictures**: the app finds the table's ruled lines, reads each cell separately with Tesseract
and rebuilds the table. It then reads it like a spreadsheet. Safety nets:

* a number that isn't read cleanly (e.g. "2a") is left blank ("not reported"), never guessed;
* on the car report each Total is checked against the level rows above it, an unreadable Total
  is replaced by the sum of the level rows, and any disagreement is shown on the review screen;
* everything is shown for checking and correction before it is saved.

Clear, uncropped screenshots read best. Blurry phone photos of a screen may need more corrections.

South African number formats are understood ("3 513", "56,36%", "13,2").
Blank cells are stored as "not reported". They are never counted as zero.
If a report's wording changes, add the new wording to the `aliases` of that field in
[`mtdapp/fields.py`](mtdapp/fields.py).

## Calculations (same as the spreadsheet)

* MTD = running sum of daily figures. If a report states its own MTD (for example the reset
  stoping series), that stated MTD is used instead.
* Plan to date = "Planned Reef Tonnes" MTD from the production report (falls back to daily call × reports received).
* Projection = reef hoisted MTD ÷ production reports × planned hoisting days.
* Equivalent hoisting days left = roster shifts after the as-at date ÷ 3.
* Required rate = (month plan − MTD hoisted) ÷ equivalent days left.
* Status: green ≥ 95 % of plan, amber ≥ 85 %, red below.
* Spillage inventory = shaft area × density × (datum − average of underlay/overlay clearance).

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
# optional: check against the real files
MTD_SAMPLE_WORKBOOK=/path/to/consolidated.xlsx MTD_SAMPLE_PDF=/path/to/daily_report.pdf \
  MTD_SAMPLE_IMAGES=/path/to/engineering.jpg,/path/to/car_report.jpg .venv/bin/python -m pytest tests
```
