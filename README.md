# 🏗️ Accela Permit Tracker

Automatically monitors your Accela Citizen Access permit portals, updates a Google Sheet with the latest status, and emails you when anything changes.

**Supports:** Hillsborough County, Pasco County, Pinellas County, Clearwater (and any other Accela ACA portal)

---

## What It Does

- Logs into your Accela accounts using a headless browser (Playwright)
- Pulls all permits from your "My Records" dashboard
- Checks permit status, inspection results, notes, and expiration dates
- Updates a Google Sheet with the latest data
- Emails you **only when something changes** — no noise, just alerts

---

## Setup (One-Time)

### 1. Fork This Repo
Click **Fork** on GitHub so you have your own copy.

### 2. Create the Google Sheet
1. Go to [Google Sheets](https://sheets.google.com) → create a new spreadsheet
2. Name it anything (e.g., "Permit Tracker")
3. Copy the Sheet ID from the URL:
   ```
   https://docs.google.com/spreadsheets/d/THIS_IS_YOUR_SHEET_ID/edit
   ```

### 3. Set Up Google Service Account
This allows the script to write to your Google Sheet.

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable **Google Sheets API** and **Google Drive API**
4. Go to **IAM & Admin → Service Accounts** → Create Service Account
5. Download the JSON key file
6. **Share your Google Sheet** with the service account email (found in the JSON as `client_email`)
7. Encode the JSON for GitHub:
   ```bash
   base64 -i your-service-account.json | tr -d '\n'
   ```
   Copy the output — this becomes your `GOOGLE_SERVICE_ACCOUNT_JSON_B64` secret.

### 4. Add GitHub Secrets
In your forked repo: **Settings → Secrets and variables → Actions → New repository secret**

Add these secrets:

| Secret Name | Value |
|------------|-------|
| `ACCELA_USERNAME_HILLSBOROUGH` | Your Hillsborough username |
| `ACCELA_PASSWORD_HILLSBOROUGH` | Your Hillsborough password |
| `GOOGLE_SHEET_ID` | Your sheet ID from step 2 |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | Base64 encoded JSON from step 3 |
| `NOTIFY_EMAIL` | Email to send alerts to |
| `SMTP_HOST` | `smtp.gmail.com` |
| `SMTP_PORT` | `587` |
| `SMTP_USER` | Your Gmail address |
| `SMTP_PASSWORD` | Your [Gmail App Password](https://support.google.com/accounts/answer/185833) |

### 5. Enable Additional Municipalities
Edit `config/municipalities.yaml` and set `enabled: true` for each county you want to monitor.

### 6. Run It
- **Automatic**: Runs Monday–Friday at 8 AM and 4 PM Eastern
- **Manual**: Go to **Actions → Permit Tracker → Run workflow**

---

## Adding More Counties
All Accela portals use the same platform. To add a new county:

1. Add an entry to `config/municipalities.yaml`
2. Add the corresponding credential secrets to GitHub
3. Set `enabled: true`

That's it. One script handles all of them.

---

## Using This For Your Contracting Business
Want to offer this as a service to other GCs or permit runners?

Each user:
1. Forks this repo
2. Adds their own credentials as GitHub Secrets
3. Connects their own Google Sheet

GitHub Actions gives each user **2,000 free minutes/month** — more than enough to run this twice daily all month.

---

## File Structure
```
permit-tracker/
├── .github/
│   └── workflows/
│       └── permit_tracker.yml    # GitHub Actions schedule
├── scraper/
│   ├── main.py                   # Entry point
│   ├── accela_scraper.py         # Playwright browser automation
│   ├── sheets_updater.py         # Google Sheets read/write
│   └── notifier.py               # Email alerts
├── config/
│   └── municipalities.yaml       # Portal URLs & settings
├── requirements.txt
├── .env.example                  # Template (never commit .env)
└── README.md
```

---

## Troubleshooting

**Login failing?**
- Double-check credentials in GitHub Secrets
- Try logging in manually at the portal URL to confirm they work

**Sheet not updating?**
- Verify the service account email has Editor access to your Google Sheet
- Check that `GOOGLE_SHEET_ID` is correct (just the ID, not the full URL)

**No email alerts?**
- For Gmail: use an [App Password](https://support.google.com/accounts/answer/185833), not your regular password
- Make sure 2-Step Verification is enabled on your Gmail account first

---

Built for Coastal Edge Renos — Tampa Bay residential remodeling.
