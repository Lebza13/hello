# Running the MTD app for use on an iPad

The app runs on a server on the internet. The iPad only uses it through Safari, like a website.
Every step below can be done on the iPad itself.

## What the pieces are

| Piece | What it is |
|---|---|
| **Dockerfile** (in this repository) | A recipe that builds a "container": a sealed box holding Python, Tesseract OCR and the app, set up the same way every time. You never run it yourself; the hosting service does. |
| **render.yaml** (in this repository) | Instructions for Render.com: build the Dockerfile, attach a 1 GB disk for the data, ask you for a password. |
| **Render.com** | A hosting company. It reads the repository from GitHub, builds the container and runs it at an `https://….onrender.com` address. Everything is done in its website. |
| **Persistent disk** | Where the database and uploaded reports are kept. Without it, history would be wiped whenever the app restarts, so it is required. |
| **MTD_PASSWORD** | The password everyone types to open the app. |

## Cost

A persistent disk needs a paid Render plan: the "Starter" web service plus a 1 GB disk, a few US dollars
a month in total. Check current prices at https://render.com/pricing. The free plan has **no disk**, so it
would lose your history. Don't use it for this app.

## One-time setup (about 15 minutes, all in Safari on the iPad)

### 1. Put the app on the main branch of your GitHub repository
The app is on the branch `claude/spreadsheet-replacement-app-f33nwd`. On github.com open
**Lebza13/hello → Pull requests → New pull request**, choose that branch, then **Create** and **Merge**.
(Or ask Claude to open the pull request for you.)

### 2. Create a Render account
Go to https://render.com, tap **Get Started**, and sign up with **GitHub**. Allow Render to see the
`Lebza13/hello` repository when GitHub asks.

### 3. Create the app from the blueprint
1. In the Render dashboard tap **New → Blueprint**.
2. Choose the repository **Lebza13/hello** (branch `master`).
3. Render reads `render.yaml` and shows one web service, `thembelani-mtd`, with a disk `mtd-data`.
4. It asks for **MTD_PASSWORD**: type a strong password (at least 12 characters) and note it down.
5. Add a payment card when asked, then tap **Apply** / **Create**.

The first build takes about 5–10 minutes (it installs Python, Tesseract and the app). When the
status shows **Live**, the address is at the top of the page, e.g. `https://thembelani-mtd.onrender.com`.

### 4. Open it on the iPad
1. Open the address in Safari and sign in with the password.
2. Tap **Share → Add to Home Screen → Add**. An "MTD" icon appears and opens the app full screen.
3. First time only: **Upload daily reports → Other files**, choose the old consolidated workbook
   (`Thembelani_Consolidated_MTD_Production_Report_….xlsx`) and press **Read files**. This loads the
   September history.

## Daily use on the iPad

1. Save the three reports on the iPad when they arrive. For example, in WhatsApp or Mail, hold
   the picture/PDF, then **Save to Photos** or **Save to Files**.
2. Open the MTD app, tap **Upload daily reports**, and fill the three boxes:
   * **Daily Production Report**: tap the box, choose **Choose File**, pick the PDF.
   * **Engineering snapshot**: tap the box, choose **Photo Library**, pick the picture.
   * **Shaft Car Report**: same, pick the car report picture.
3. Tap **Read files** and wait about 20 seconds.
4. Check every figure against the pictures, correct anything wrong, and tap **Save to history**.
5. The dashboard updates. **Download consolidated Excel** saves the workbook to Files for sharing.

## Backups (weekly)

**Settings → Download backup** saves one `.db` file with all history. Keep it in iCloud Drive or
OneDrive. To move to a new server, or to recover, use **Settings → Restore a backup** with that file.

## Updating the app later

When changes are merged into `master` on GitHub, Render rebuilds and restarts the app
automatically. The data on the disk is kept.

## Changing the password

Render dashboard → **thembelani-mtd → Environment → MTD_PASSWORD → Edit → Save**. The app restarts
with the new password (everyone signs in again).

## If something goes wrong

| Problem | What to do |
|---|---|
| Page says "Service Unavailable" right after setup | The first build is still running. Wait for **Live**. |
| Pictures give "Reading images needs Tesseract" | The service was not built from the Dockerfile. Check it is a *Docker* service. |
| History disappeared after a restart | No disk is attached. Render → service → **Disks** must show `/data`. |
| Upload stops with an error after ~30 s | Render → service → **Logs** shows the reason. Send it to Claude. |

## Other hosts

The same Dockerfile runs anywhere containers run (Azure App Service, AWS, a company server with
Docker). The only requirements are to keep `/data` on persistent storage and set `MTD_PASSWORD`:

```
docker build -t mtd-app .
docker run -d -p 8000:8000 -v mtd-data:/data -e MTD_PASSWORD='choose-a-strong-one' mtd-app
```
