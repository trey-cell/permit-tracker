"""
accela_scraper.py
-----------------
Uses Skyvern AI browser automation to log into Accela Citizen Access portals,
navigate to My Records, and extract permit data.

No brittle selectors needed — Skyvern visually reads the page like a human.
"""

import os
import time
import logging
import requests
from dataclasses import dataclass

logger = logging.getLogger(__name__)

SKYVERN_API_URL = "https://api.skyvern.com/api/v1"
MAX_WAIT_SECONDS = 600   # 10 minute max per county
POLL_INTERVAL    = 15    # check every 15 seconds


@dataclass
class PermitRecord:
    permit_number:    str
    address:          str
    municipality:     str
    permit_type:      str = ""
    status:           str = ""
    applied_date:     str = ""
    issued_date:      str = ""
    expiration_date:  str = ""
    last_inspection:  str = ""
    inspection_result: str = ""
    notes:            str = ""
    detail_url:       str = ""


def scrape_municipality(config: dict) -> list[PermitRecord]:
    """
    Use Skyvern to log into an Accela portal and extract all permit records
    from the My Records page.
    """
    api_key   = os.environ.get("SKYVERN_API_KEY", "")
    username  = os.environ.get(config["username_env"], "")
    password  = os.environ.get(config["password_env"], "")
    muni_name = config["name"]

    if not api_key:
        raise ValueError("SKYVERN_API_KEY is not set.")
    if not username or not password:
        logger.warning(f"Skipping {muni_name} — credentials not set.")
        return []

    headers = {
        "x-api-key": api_key,
        "Content-Type": "application/json"
    }

    navigation_goal = f"""
     You are logging into the Hillsborough County Accela Citizen Access permit portal.
    Follow these steps exactly in order:

  STEP 1 - LOGIN:
    - The login form is inside an embedded panel or iframe on the page
    - Find the username and password fields visually
    - Enter username: {username}
    - Enter password: {password}
    - Click the Sign In button
    - Wait for the homepage to fully load after login

    STEP 2 - NAVIGATE TO COLLECTIONS:
    - After login you will be on the homepage
    - Look at the top right of the page — there is a navigation bar with multiple items
    - You will see options like: Logout, My Account, Cart, Collections, and "Logged in as Trey Rhyne"
    - Click on "Collections" in that top right navigation bar

    STEP 3 - READ ALL COLLECTION NAMES BEFORE CLICKING ANYTHING:
    - On the Collections page, scroll down until you see the table
    - The table has columns: Date Modified, Name, Description, Number of Records
    - The "Name" column shows all addresses of active permits listed in rows
    - Before clicking anything, count and note ALL rows in the table (example: row 1 = 12137 Stonelake, row 2 = 12501 Clydesdale, row 3 = 4812 Rambling, row 4 = 6145 Durant Rd)
    - You must visit EVERY row — do not stop after the first one

    STEP 4 - VISIT ADDRESS ROW 1 (first row only):
    - Click the address NAME link in the FIRST row of the collections table
    - Wait for the permit records table to load — it will show columns:
      Date, Record Number, Record Type, Address, Description, Project Name, Expiration Date, Status
    - Read and remember ALL permit data shown on this page
    - When done reading, click the BACK button to return to the Collections page
    - Wait for the Collections page to fully reload before continuing

    STEP 5 - VISIT ADDRESS ROW 2 (second row only):
    - You are back on the Collections page
    - Click the address NAME link in the SECOND row — this is a DIFFERENT address than step 4
    - Wait for the permit records table to load
    - Read and remember ALL permit data shown on this page
    - When done reading, click the BACK button to return to the Collections page
    - Wait for the Collections page to fully reload before continuing

    STEP 6 - VISIT ADDRESS ROW 3 (third row only):
    - You are back on the Collections page
    - Click the address NAME link in the THIRD row — this is a DIFFERENT address than steps 4 and 5
    - Wait for the permit records table to load
    - Read and remember ALL permit data shown on this page
    - When done reading, click the BACK button to return to the Collections page
    - Wait for the Collections page to fully reload before continuing

    STEP 7 - VISIT ADDRESS ROW 4 (fourth row only):
    - You are back on the Collections page
    - Click the address NAME link in the FOURTH row — this is a DIFFERENT address than all previous steps
    - Wait for the permit records table to load
    - Read and remember ALL permit data shown on this page
    - You are now done navigating — proceed to extract all collected permit data

    CRITICAL RULES:
    - Each step must click a DIFFERENT row than all previous steps — never click the same address twice
    - Keep track of which row number you are on — row 1, row 2, row 3, row 4, etc.
    - If you find yourself on a page you already visited, go back and click the next row you have NOT visited yet
    - If there are more than 4 addresses, continue the same pattern for rows 5, 6, etc.
    - If an address row has 0 permit records, go back and continue to the next row

    Important: The portal uses Angular components. Always look for what is visually on screen.
    """

    data_extraction_goal = """
    Extract ALL permit records found across ALL collections.

    For each permit record in each collection capture these exact fields:
    - permit_number: The "Record Number" column — this is the unique permit identifier (e.g., BCP-123456-2025)
    - permit_type: The "Record Type" column — the type of permit (e.g., Building, Electrical, Plumbing, Re-Roof)
    - address: The "Address" column — the full property street address for this permit
    - expiration_date: The "Expiration Date" column — the date the permit expires in MM/DD/YYYY format
    - status: The "Status" column — current permit status (e.g., Issued, Approved, Under Review, Expired, Finaled)

    Rules:
    - Record Number = Permit Number — use the Record Number column for permit_number
    - Do NOT include header rows, blank rows, or rows without a Record Number
    - If Expiration Date is blank or not shown, return an empty string
    - Capture permits from ALL collections, not just the first one
    - Do not skip any permit rows
    """
    extracted_information_schema = {
        "type": "object",
        "properties": {
            "permits": {
                "type": "array",
                "description": "All permit records found in the My Records table",
                "items": {
                    "type": "object",
                    "properties": {
                        "permit_number":   {"type": "string"},
                        "address":         {"type": "string"},
                        "permit_type":     {"type": "string"},
                        "status":          {"type": "string"},
                        "applied_date":    {"type": "string"},
                        "expiration_date": {"type": "string"}
                    },
                    "required": ["permit_number"]
                }
            }
        }
    }

    # ── Create Skyvern task ────────────────────────────────────────────────────
    logger.info(f"Creating Skyvern task for {muni_name}...")

    task_payload = {
        "url":                          config["login_url"],
        "navigation_goal":              navigation_goal,
        "data_extraction_goal":         data_extraction_goal,
        "extracted_information_schema": extracted_information_schema,
    }

    resp = requests.post(
        f"{SKYVERN_API_URL}/tasks",
        json=task_payload,
        headers=headers,
        timeout=30
    )

    if resp.status_code not in (200, 201):
        logger.error(f"Skyvern task creation failed [{resp.status_code}]: {resp.text}")
        return []

    task_id = resp.json().get("task_id")
    if not task_id:
        logger.error(f"No task_id in Skyvern response: {resp.json()}")
        return []

    logger.info(f"Skyvern task created: {task_id} — polling every {POLL_INTERVAL}s...")

    # ── Poll for completion ────────────────────────────────────────────────────
    elapsed = 0
    while elapsed < MAX_WAIT_SECONDS:
        time.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

        poll_resp = requests.get(
            f"{SKYVERN_API_URL}/tasks/{task_id}",
            headers=headers,
            timeout=30
        )

        if poll_resp.status_code != 200:
            logger.warning(f"Poll error [{poll_resp.status_code}] at {elapsed}s — retrying...")
            continue

        task_data   = poll_resp.json()
        task_status = task_data.get("status", "")
        logger.info(f"  Task {task_id}: {task_status} ({elapsed}s elapsed)")

        if task_status == "completed":
            return _parse_skyvern_result(task_data, muni_name)

        if task_status in ("failed", "terminated", "timed_out"):
            reason = task_data.get("failure_reason", "unknown reason")
            logger.error(f"Skyvern task {task_id} ended with '{task_status}': {reason}")
            return []

    logger.error(f"Timed out waiting for Skyvern task {task_id} after {MAX_WAIT_SECONDS}s.")
    return []


def _parse_skyvern_result(task_data: dict, municipality: str) -> list[PermitRecord]:
    """Convert Skyvern extracted_information into PermitRecord objects."""
    extracted = task_data.get("extracted_information") or {}

    if isinstance(extracted, str):
        import json
        try:
            extracted = json.loads(extracted)
        except Exception:
            logger.error(f"Could not parse extracted_information as JSON: {extracted[:200]}")
            return []

    permits_data = extracted.get("permits", [])
    logger.info(f"Skyvern returned {len(permits_data)} permits for {municipality}.")

    records = []
    for p in permits_data:
        num = (p.get("permit_number") or "").strip()
        if not num:
            continue
        records.append(PermitRecord(
            permit_number   = num,
            address         = (p.get("address")         or "").strip(),
            municipality    = municipality,
            permit_type     = (p.get("permit_type")     or "").strip(),
            status          = (p.get("status")          or "").strip(),
            applied_date    = (p.get("applied_date")    or "").strip(),
            expiration_date = (p.get("expiration_date") or "").strip(),
        ))

    return records
