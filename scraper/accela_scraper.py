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

            # ── Step 2: Wait for full JS load & inspect page ───────────────────
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass
            page.wait_for_timeout(2000)

            # Log all frames on page
            frames = page.frames
            logger.info(f"Frames on page: {[f.url for f in frames]}")

            # Log all inputs across ALL frames
            for i, frame in enumerate(frames):
                try:
                    inputs_info = frame.evaluate("""() => {
                        const inputs = document.querySelectorAll('input');
                        return Array.from(inputs).map(inp => ({
                            id: inp.id,
                            name: inp.name,
                            type: inp.type,
                            placeholder: inp.placeholder,
                            autocomplete: inp.autocomplete,
                            visible: inp.offsetParent !== null
                        }));
                    }""")
                    logger.info(f"Frame {i} ({frame.url}) inputs: {inputs_info}")
                except Exception as e:
                    logger.info(f"Frame {i} ({frame.url}) could not be inspected: {e}")

            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_2_before_fill")

            # ── Step 3: Fill login form (try main page + all iframes) ──────────
            username_filled = False
            password_filled = False
            active_frame = None

            all_frames = [page] + list(page.frames[1:])  # main page first, then iframes

            for frame in all_frames:
                if username_filled:
                    break
                frame_url = frame.url if hasattr(frame, 'url') else 'main'

                # Try by label first
                for label_text in ["USERNAME OR EMAIL", "Username or Email", "Username", "User Name", "Email"]:
                    try:
                        locator = frame.get_by_label(label_text, exact=False)
                        locator.wait_for(timeout=2000)
                        locator.fill(username)
                        logger.info(f"Filled username via get_by_label '{label_text}' in frame: {frame_url}")
                        username_filled = True
                        active_frame = frame
                        break
                    except Exception:
                        continue

                # Try by selector
                if not username_filled:
                    for sel in ["#ctl00_PlaceHolderMain_LoginSection_txtUserName",
                                "input[id*='UserName']", "input[id*='LoginName']",
                                "input[name*='UserName']", "input[name*='LoginName']",
                                "input[type='email']", "input[autocomplete='username']"]:
                        try:
                            frame.wait_for_selector(sel, timeout=2000)
                            frame.fill(sel, username)
                            logger.info(f"Filled username via selector '{sel}' in frame: {frame_url}")
                            username_filled = True
                            active_frame = frame
                            break
                        except Exception:
                            continue

            if not username_filled:
                _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_login_fill_failed")
                logger.error(f"Could not find username field in any frame.")
                return []

            # Fill password in same frame
            frame = active_frame
            frame_url = frame.url if hasattr(frame, 'url') else 'main'

            for label_text in ["PASSWORD", "Password"]:
                try:
                    locator = frame.get_by_label(label_text, exact=False)
                    locator.wait_for(timeout=2000)
                    locator.fill(password)
                    logger.info(f"Filled password via get_by_label '{label_text}' in frame: {frame_url}")
                    password_filled = True
                    break
                except Exception:
                    continue

            if not password_filled:
                for sel in ["#ctl00_PlaceHolderMain_LoginSection_txtPassword",
                            "input[id*='Password']", "input[name*='Password']",
                            "input[type='password']", "input[autocomplete='current-password']"]:
                    try:
                        frame.wait_for_selector(sel, timeout=2000)
                        frame.fill(sel, password)
                        logger.info(f"Filled password via selector '{sel}' in frame: {frame_url}")
                        password_filled = True
                        break
                    except Exception:
                        continue

            if not password_filled:
                _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_login_fill_failed")
                logger.error(f"Could not find password field.")
                return []

            # ── Step 4: Click login button ─────────────────────────────────────
            _save_screenshot(page, f"{municipality_name.replace(' ', '_')}_3_login_filled")

            # Login button is an Angular PrimeNG button — use get_by_role (most reliable)
            clicked = False
            for btn_name in ["Sign In", "Log In", "LOGIN", "SIGN IN", "Submit"]:
                try:
                    btn = active_frame.get_by_role("button", name=btn_name)
                    btn.wait_for(state="visible", timeout=5000)
                    btn.click()
                    clicked = True
                    logger.info(f"Clicked login button via get_by_role name='{btn_name}'")
                    break
                except Exception:
                    pass

            # Fallback: CSS selectors
            if not clicked:
                login_btn_selectors = [
                    "button.ACA_Button",
                    "button[pbutton]",
                    "button.p-button",
                    "#btnLogin",
                    "input[type='submit']",
                    "button[type='submit']",
                    "button",
                ]
                clicked = _try_click(active_frame, login_btn_selectors, "login button")

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
