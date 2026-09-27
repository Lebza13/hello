# Thembelani MTD Production app

A small web app that replaces the consolidated MTD production spreadsheet.
Each day you upload the three daily reports and the app:

* reads the figures and shows them to you before saving,
* keeps every day in a local database (`data/mtd.db`), so history builds up month after month,
* recalculates the month-to-date dashboard (mining, daily call, material flow, recovery,
  engineering, spillage, logistics, exceptions),
* lets you download a consolidated Excel workbook for any month.

## Start it

Needs Python 3.10 or newer.

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

1. **Upload daily reports**: pick the Daily Production Report, Engineering Daily Snapshot
   and Material Car Report. They can be three files or one workbook with three sheets.
2. Check the figures on the review screen, correct a date if needed, and press **Save to history**.
   Uploading the same date again replaces it.
3. The **Dashboard** now shows the new position. **Download consolidated Excel** gives the
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

The app looks for known labels (for example *Reef Hoisted*, *Cars Down*, *Underlay*) anywhere
in each sheet and takes the number in the cell to the right, or directly below. A *Date* label
gives the report date. If there's no date in the file, the date in the file name is used, then the date typed on the upload form.
A sheet with a *Date* column and one row per day also works, which is useful for back-filling.

Blank cells are stored as "not reported". They are never counted as zero.

If your real reports use different wording, add it to the `aliases` of the field in
[`mtdapp/fields.py`](mtdapp/fields.py). Blank input templates for each report can be
downloaded from the Upload page.

## Calculations (same as the spreadsheet)

* MTD = running sum of daily figures. If a report states its own MTD (for example the reset
  stoping series), that stated MTD is used instead.
* Plan to date = daily call × production reports received this month.
* Projection = reef hoisted MTD ÷ production reports × planned hoisting days.
* Equivalent hoisting days left = roster shifts after the as-at date ÷ 3.
* Required rate = (month plan − MTD hoisted) ÷ equivalent days left.
* Status: green ≥ 95 % of plan, amber ≥ 85 %, red below.
* Spillage inventory = shaft area × density × (datum − average of underlay/overlay clearance).

## Tests

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest tests
# optional: check the history import against the old workbook
MTD_SAMPLE_WORKBOOK=/path/to/consolidated.xlsx .venv/bin/python -m pytest tests
```
