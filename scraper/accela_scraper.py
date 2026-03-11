"""
accela_scraper.py
-----------------
Logs into an Accela Citizen Access portal using Playwright (headless browser),
navigates to the user's My Records / Dashboard, and extracts permit details:
  - Permit number
  - Address
  - Type
  - Status
  - Applied / Issued / Expiration dates
  - Last inspection result
  - Notes / comments from the municipality
"""

import os
import time
import logging
from dataclasses import dataclass, field
from typing import Optional
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)


@dataclass
class PermitRecord:
    permit_number: str
    address: str
    municipality: str
    permit_type: str = ""
    status: str = ""
    applied_date: str = ""
    issued_date: str = ""
    expiration_date: str = ""
    last_inspection: str = ""
    inspection_result: str = ""
    notes: str = ""
    detail_url: str = ""


def scrape_municipality(config: dict) -> list[PermitRecord]:
    """
    Scrape all permit records for a given municipality config.
    config keys: name, base_url, login_url, dashboard_url,
                 username_env, password_env
    """
    username = os.environ.get(config["username_env"], "")
    password = os.environ.get(config["password_env"], "")
    municipality_name = config["name"]

    if not username or not password:
        logger.warning(f"Skipping {municipality_name} — credentials not set.")
        return []

    records = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                       "AppleWebKit/537.36 (KHTML, like Gecko) "
                       "Chrome/121.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        try:
            # ── Step 1: Login ──────────────────────────────────────────────────
            logger.info(f"Logging into {municipality_name}...")
            page.goto(config["login_url"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)

            # Fill login form — Accela uses consistent field IDs across portals
            page.fill('input[id*="txtLoginName"], input[name*="LoginName"], #txtUserName', username)
            page.fill('input[id*="txtPassword"], input[name*="Password"], #txtPassword', password)
            page.click('input[id*="btnLogin"], input[type="submit"], button[type="submit"]')
            page.wait_for_load_state("networkidle", timeout=15000)

            if "Login" in page.title() or "login" in page.url:
                logger.error(f"Login failed for {municipality_name}. Check credentials.")
                return []

            logger.info(f"Logged in to {municipality_name} successfully.")

            # ── Step 2: Go to My Records (Dashboard) ──────────────────────────
            page.goto(config["dashboard_url"], wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            # ── Step 3: Collect all permit rows from the dashboard ─────────────
            records = _parse_dashboard(page, municipality_name, config["base_url"])
            logger.info(f"Found {len(records)} permits in {municipality_name}.")

        except PlaywrightTimeout as e:
            logger.error(f"Timeout scraping {municipality_name}: {e}")
        except Exception as e:
            logger.error(f"Error scraping {municipality_name}: {e}", exc_info=True)
        finally:
            context.close()
            browser.close()

    return records


def _parse_dashboard(page: Page, municipality: str, base_url: str) -> list[PermitRecord]:
    """Parse the My Records dashboard page for permit rows."""
    records = []

    # Wait for records table to appear
    try:
        page.wait_for_selector("table.ACA_Grid_Table, #tblPermitList, .portlet-content", timeout=10000)
    except PlaywrightTimeout:
        logger.warning("No records table found on dashboard — may be empty or layout changed.")
        return records

    # Grab all rows — Accela uses consistent class names
    rows = page.query_selector_all("tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even, tr[class*='TabRow']")
    
    if not rows:
        # Try alternative selectors for newer Accela versions
        rows = page.query_selector_all("table[id*='PermitList'] tr:not(:first-child), .grid-row")

    for row in rows:
        try:
            cells = row.query_selector_all("td")
            if len(cells) < 3:
                continue

            # Extract permit number and detail link
            permit_link = row.query_selector("a[href*='CapDetail'], a[href*='capId']")
            permit_number = permit_link.inner_text().strip() if permit_link else ""
            detail_url = ""
            if permit_link:
                href = permit_link.get_attribute("href") or ""
                detail_url = href if href.startswith("http") else base_url + "/" + href.lstrip("/")

            if not permit_number:
                continue

            # Map cell text to fields (order varies slightly by portal version)
            cell_texts = [c.inner_text().strip() for c in cells]

            record = PermitRecord(
                permit_number=permit_number,
                municipality=municipality,
                address=_find_cell(cell_texts, 1),
                permit_type=_find_cell(cell_texts, 2),
                status=_find_cell(cell_texts, 3),
                applied_date=_find_cell(cell_texts, 4),
                detail_url=detail_url,
            )

            # ── Step 4: Drill into detail page for more info ───────────────────
            if detail_url:
                _enrich_from_detail(page, record, detail_url)

            records.append(record)

        except Exception as e:
            logger.warning(f"Error parsing row: {e}")
            continue

    return records


def _enrich_from_detail(page: Page, record: PermitRecord, detail_url: str):
    """Visit the permit detail page to get inspection history and notes."""
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(2000)

        # ── Expiration / Issued dates ──────────────────────────────────────────
        for label_text in ["Expiration Date", "Expire Date"]:
            el = page.query_selector(f"span:text('{label_text}') + span, td:text('{label_text}') + td")
            if el:
                record.expiration_date = el.inner_text().strip()
                break

        for label_text in ["Issued Date", "Issue Date"]:
            el = page.query_selector(f"span:text('{label_text}') + span, td:text('{label_text}') + td")
            if el:
                record.issued_date = el.inner_text().strip()
                break

        # ── Inspections tab ────────────────────────────────────────────────────
        insp_tab = page.query_selector("a[href*='Inspection'], li:text('Inspections')")
        if insp_tab:
            insp_tab.click()
            page.wait_for_timeout(2000)
            insp_rows = page.query_selector_all(
                "table[id*='Inspection'] tr:not(:first-child), .inspection-row"
            )
            if insp_rows:
                # Most recent inspection is usually first
                first = insp_rows[0].query_selector_all("td")
                if first:
                    texts = [c.inner_text().strip() for c in first]
                    record.last_inspection = _find_cell(texts, 0)
                    record.inspection_result = _find_cell(texts, 2)

        # ── Notes / Comments ───────────────────────────────────────────────────
        notes_tab = page.query_selector("a[href*='Notes'], a[href*='Comment'], li:text('Notes')")
        if notes_tab:
            notes_tab.click()
            page.wait_for_timeout(2000)
            note_els = page.query_selector_all(
                ".ACA_NoteText, td[id*='comment'], .note-text, textarea[id*='Notes']"
            )
            note_texts = [n.inner_text().strip() for n in note_els if n.inner_text().strip()]
            record.notes = " | ".join(note_texts[:3])  # Keep top 3 notes

    except Exception as e:
        logger.debug(f"Could not enrich detail for {record.permit_number}: {e}")

    finally:
        # Navigate back
        try:
            page.go_back(wait_until="domcontentloaded", timeout=10000)
        except Exception:
            pass


def _find_cell(texts: list, index: int) -> str:
    """Safely get cell text by index."""
    try:
        return texts[index] if index < len(texts) else ""
    except (IndexError, TypeError):
        return ""
