"""
accela_scraper.py
-----------------
Logs into an Accela Citizen Access portal using Playwright (headless browser),
navigates to My Records, and extracts permit details.
"""

import os
import logging
from dataclasses import dataclass
from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = "/tmp/screenshots"


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


def _save_screenshot(page: Page, name: str):
    """Save a debug screenshot."""
    try:
        os.makedirs(SCREENSHOT_DIR, exist_ok=True)
        path = f"{SCREENSHOT_DIR}/{name}.png"
        page.screenshot(path=path)
        logger.info(f"Screenshot saved: {path}")
    except Exception as e:
        logger.debug(f"Could not save screenshot: {e}")


def _try_fill(page: Page, selectors: list, value: str, label: str) -> bool:
    """Try each selector in order until one works."""
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=5000)
            page.fill(sel, value)
            logger.info(f"Filled {label} using selector: {sel}")
            return True
        except Exception:
            continue
    logger.error(f"Could not find {label} field. Tried: {selectors}")
    return False


def _try_click(page: Page, selectors: list, label: str) -> bool:
    """Try each selector in order until one works."""
    for sel in selectors:
        try:
            page.wait_for_selector(sel, timeout=5000)
            page.click(sel)
            logger.info(f"Clicked {label} using selector: {sel}")
            return True
        except Exception:
            continue
    logger.error(f"Could not find {label} button. Tried: {selectors}")
    return False


def scrape_municipality(config: dict) -> list[PermitRecord]:
    """
    Scrape all permit records for a given municipality config.
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
            # ── Step 1: Load login page ────────────────────────────────────────
            logger.info(f"Loading login page for {municipality_name}...")
            page.goto(config["login_url"], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(3000)
            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_1_login_page")
            logger.info(f"Login page title: {page.title()}")
            logger.info(f"Login page URL: {page.url}")

            # ── Step 2: Fill login form ────────────────────────────────────────
            username_selectors = [
                "#txtLoginName",
                "input[name='LoginName']",
                "input[id$='LoginName']",
                "#txtUserName",
                "input[type='text']",
            ]
            password_selectors = [
                "#txtPassword",
                "input[name='Password']",
                "input[id$='Password']",
                "input[type='password']",
            ]
            login_btn_selectors = [
                "#btnLogin",
                "input[id$='btnLogin']",
                "input[value='Login']",
                "input[type='submit']",
                "button[type='submit']",
            ]

            filled_user = _try_fill(page, username_selectors, username, "username")
            filled_pass = _try_fill(page, password_selectors, password, "password")

            if not filled_user or not filled_pass:
                _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_2_login_fill_failed")
                logger.error(f"Could not fill login form for {municipality_name}")
                return []

            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_2_login_filled")

            clicked = _try_click(page, login_btn_selectors, "login button")
            if not clicked:
                _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_3_login_click_failed")
                return []

            # Wait for navigation after login
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except PlaywrightTimeout:
                page.wait_for_load_state("load", timeout=10000)

            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_3_after_login")
            logger.info(f"After login - Title: {page.title()}, URL: {page.url}")

            if "login" in page.url.lower() or "Login" in page.title():
                logger.error(f"Login failed for {municipality_name} — still on login page.")
                return []

            logger.info(f"Logged in to {municipality_name} successfully.")

            # ── Step 3: Go to My Records ───────────────────────────────────────
            logger.info(f"Navigating to My Records: {config['dashboard_url']}")
            page.goto(config["dashboard_url"], wait_until="domcontentloaded", timeout=45000)
            page.wait_for_timeout(4000)
            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_4_my_records")
            logger.info(f"My Records page title: {page.title()}")
            logger.info(f"My Records URL: {page.url}")

            # Log page content snippet for debugging
            try:
                body_text = page.inner_text("body")[:500]
                logger.info(f"Page content preview: {body_text}")
            except Exception:
                pass

            # ── Step 4: Parse permit rows ──────────────────────────────────────
            records = _parse_records_page(page, municipality_name, config["base_url"])
            logger.info(f"Found {len(records)} permits in {municipality_name}.")

        except PlaywrightTimeout as e:
            logger.error(f"Timeout scraping {municipality_name}: {e}")
            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_error_timeout")
        except Exception as e:
            logger.error(f"Error scraping {municipality_name}: {e}", exc_info=True)
            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_error_general")
        finally:
            context.close()
            browser.close()

    return records


def _parse_records_page(page: Page, municipality: str, base_url: str) -> list[PermitRecord]:
    """Parse the My Records page for permit rows."""
    records = []

    # Try multiple table selectors Accela uses
    table_selectors = [
        "table.ACA_Grid_Table",
        "#tblPermitList",
        "table[id*='GridViewBuildingPermit']",
        "table[id*='PermitList']",
        "table[id*='Cap']",
        ".portlet-content table",
        "table",
    ]

    found_table = False
    for sel in table_selectors:
        try:
            page.wait_for_selector(sel, timeout=8000)
            logger.info(f"Found table with selector: {sel}")
            found_table = True
            break
        except PlaywrightTimeout:
            continue

    if not found_table:
        logger.warning("No records table found — page may be empty or layout changed.")
        try:
            logger.info(f"Full page text: {page.inner_text('body')[:1000]}")
        except Exception:
            pass
        return records

    # Try multiple row selectors
    rows = []
    row_selectors = [
        "tr.ACA_TabRow_Odd, tr.ACA_TabRow_Even",
        "tr[class*='TabRow']",
        "tr[class*='Row']",
        "table.ACA_Grid_Table tr:not(:first-child)",
        "tbody tr",
    ]

    for sel in row_selectors:
        try:
            rows = page.query_selector_all(sel)
            if rows:
                logger.info(f"Found {len(rows)} rows with selector: {sel}")
                break
        except Exception:
            continue

    if not rows:
        logger.warning("No data rows found in table.")
        return records

    for row in rows:
        try:
            cells = row.query_selector_all("td")
            if len(cells) < 2:
                continue

            # Look for permit number link
            permit_link = row.query_selector("a[href*='CapDetail'], a[href*='capId'], a[href*='Cap/']")
            permit_number = permit_link.inner_text().strip() if permit_link else ""

            detail_url = ""
            if permit_link:
                href = permit_link.get_attribute("href") or ""
                detail_url = href if href.startswith("http") else base_url + "/" + href.lstrip("/")

            if not permit_number:
                # Try getting first cell text as permit number
                permit_number = cells[0].inner_text().strip()

            if not permit_number or permit_number.lower() in ["permit number", "record number", ""]:
                continue

            cell_texts = [c.inner_text().strip() for c in cells]
            logger.debug(f"Row cells: {cell_texts}")

            record = PermitRecord(
                permit_number=permit_number,
                municipality=municipality,
                address=_find_cell(cell_texts, 1),
                permit_type=_find_cell(cell_texts, 2),
                status=_find_cell(cell_texts, 3),
                applied_date=_find_cell(cell_texts, 4),
                detail_url=detail_url,
            )

            records.append(record)

        except Exception as e:
            logger.warning(f"Error parsing row: {e}")
            continue

    return records


def _find_cell(texts: list, index: int) -> str:
    """Safely get cell text by index."""
    try:
        return texts[index] if index < len(texts) else ""
    except (IndexError, TypeError):
        return ""
