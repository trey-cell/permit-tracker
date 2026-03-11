"""
sheets_updater.py
-----------------
Reads/writes permit data to a Google Sheet.

Sheet structure (auto-created if missing):
  Col A: Permit #
  Col B: Address
  Col C: Municipality
  Col D: Type
  Col E: Status
  Col F: Applied Date
  Col G: Issued Date
  Col H: Expiration Date
  Col I: Last Inspection
  Col J: Inspection Result
  Col K: Notes
  Col L: Last Checked
  Col M: Previous Status   (for change detection)
  Col N: Changed?          (YES / — )
  Col O: Detail URL
"""

import os
import base64
import json
import logging
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials
from accela_scraper import PermitRecord

logger = logging.getLogger(__name__)

SHEET_NAME = "Permit Tracker"
HEADER = [
    "Permit #", "Address", "Municipality", "Type",
    "Status", "Applied Date", "Issued Date", "Expiration Date",
    "Last Inspection", "Inspection Result", "Notes",
    "Last Checked", "Previous Status", "Changed?", "Detail URL"
]


def _get_client():
    """Authenticate to Google Sheets using service account JSON from env."""
    b64 = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON_B64", "")
    if not b64:
        raise ValueError("GOOGLE_SERVICE_ACCOUNT_JSON_B64 is not set.")
    
    creds_json = json.loads(base64.b64decode(b64).decode("utf-8"))
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_json, scopes=scopes)
    return gspread.authorize(creds)


def _get_or_create_worksheet(spreadsheet) -> gspread.Worksheet:
    """Get the Permit Tracker sheet, creating it with headers if needed."""
    try:
        ws = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title=SHEET_NAME, rows=500, cols=len(HEADER))
        ws.append_row(HEADER)
        # Bold the header row
        ws.format("A1:O1", {"textFormat": {"bold": True}})
        logger.info(f"Created new worksheet: {SHEET_NAME}")
    return ws


def update_sheet(records: list[PermitRecord]) -> list[PermitRecord]:
    """
    Update the Google Sheet with fresh permit data.
    Returns list of records where status/inspection changed.
    """
    sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
    if not sheet_id:
        raise ValueError("GOOGLE_SHEET_ID is not set.")

    client = _get_client()
    spreadsheet = client.open_by_key(sheet_id)
    ws = _get_or_create_worksheet(spreadsheet)

    # Load existing data into a dict keyed by permit number
    existing_rows = ws.get_all_records()
    existing = {row["Permit #"]: row for row in existing_rows if row.get("Permit #")}

    changed_records = []
    now = datetime.now().strftime("%m/%d/%Y %I:%M %p")
    rows_to_write = []

    for rec in records:
        prev = existing.get(rec.permit_number, {})
        prev_status = prev.get("Status", "")
        prev_inspection = prev.get("Last Inspection", "")

        # Detect changes
        changed = (
            (prev_status and prev_status != rec.status) or
            (prev_inspection and prev_inspection != rec.last_inspection)
        )

        if changed:
            changed_records.append(rec)
            logger.info(f"CHANGE DETECTED: {rec.permit_number} — status: '{prev_status}' → '{rec.status}'")

        row = [
            rec.permit_number,
            rec.address,
            rec.municipality,
            rec.permit_type,
            rec.status,
            rec.applied_date,
            rec.issued_date,
            rec.expiration_date,
            rec.last_inspection,
            rec.inspection_result,
            rec.notes,
            now,
            prev_status or rec.status,     # previous status
            "🔴 YES" if changed else "—",
            rec.detail_url,
        ]
        rows_to_write.append((rec.permit_number, row))

    # Write updates — update existing rows, append new ones
    all_permit_numbers = [r[0]["Permit #"] for r in enumerate(existing_rows)]
    
    # Get current row count for position lookup
    all_values = ws.get_all_values()
    permit_col = [r[0] for r in all_values]  # Column A (Permit #)

    for permit_number, row_data in rows_to_write:
        try:
            if permit_number in permit_col:
                row_idx = permit_col.index(permit_number) + 1  # 1-indexed
                ws.update(f"A{row_idx}:O{row_idx}", [row_data])
            else:
                ws.append_row(row_data)
        except Exception as e:
            logger.error(f"Error writing row for {permit_number}: {e}")

    logger.info(f"Sheet updated: {len(rows_to_write)} permits written, {len(changed_records)} changed.")
    return changed_records
