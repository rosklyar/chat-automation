import argparse
import csv
import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


def handle_login_modal(page):
    """
    Handle the ChatGPT login modal by clicking "Stay logged out".

    Args:
        page: Playwright page object

    Returns:
        True if modal was handled, False if not present
    """
    try:
        # Wait for the "Stay logged out" button/link to appear
        stay_logged_out = page.get_by_text("Stay logged out")

        # Check if it's visible within 5 seconds
        if stay_logged_out.is_visible(timeout=5000):
            print("Login modal detected, clicking 'Stay logged out'...")
            stay_logged_out.click()
            page.wait_for_timeout(2000)  # Wait for modal to close
            print("✓ Stayed logged out")
            return True
    except Exception as e:
        # Modal not present or already dismissed - this is fine
        pass

    return False


def save_session(context, session_file: str):
    """
    Save browser context state (cookies, storage) to file.

    Args:
        context: Playwright browser context
        session_file: Path to save session data

    Returns:
        True if successful, False otherwise
    """
    try:
        context.storage_state(path=session_file)
        print(f"✓ Session saved to {session_file}")
        return True
    except Exception as e:
        print(f"✗ Failed to save session: {e}")
        return False


def load_session(context, session_file: str):
    """
    Load browser context state from file.

    Args:
        context: Playwright browser context (not used, for API consistency)
        session_file: Path to session file

    Returns:
        True if file exists and is readable, False otherwise
    """
    try:
        if os.path.exists(session_file):
            print(f"✓ Found session file: {session_file}")
            return True
        else:
            print(f"⚠ No session file found at {session_file}")
            return False
    except Exception as e:
        print(f"✗ Error checking session file: {e}")
        return False


def is_logged_in(page) -> bool:
    """
    Check if user is logged in to ChatGPT by verifying chat interface presence.

    Args:
        page: Playwright page object

    Returns:
        True if logged in, False otherwise
    """
    try:
        # Navigate to ChatGPT
        page.goto("https://chatgpt.com/", timeout=60000)
        page.wait_for_load_state("domcontentloaded")

        # Check for chat interface (indicates logged in)
        textarea = page.locator("#prompt-textarea")
        textarea.wait_for(timeout=10000, state="visible")

        print("✓ Session validated - user is logged in")
        return True
    except Exception as e:
        print(f"⚠ Session validation failed: {e}")
        return False


def wait_for_manual_login(page):
    """
    Wait for user to manually log in to ChatGPT.

    Args:
        page: Playwright page object

    Returns:
        True if ready to continue, False on error
    """
    print("\n" + "="*60)
    print("MANUAL LOGIN REQUIRED")
    print("="*60)
    print("Please log in to ChatGPT in the browser window.")
    print("This enables cited sources in responses.")
    print()
    print("After logging in:")
    print("  1. Wait for the chat interface to load")
    print("  2. Press Enter in this terminal to continue...")
    print("="*60)

    try:
        # Wait for user confirmation
        input()

        print("\n✓ Continuing with automation...")

        # Verify chat interface is ready
        textarea = page.locator("#prompt-textarea")
        textarea.wait_for(timeout=10000)
        print("✓ Chat interface verified and ready!")

        return True
    except Exception as e:
        print(f"✗ Error: {e}")
        print("Make sure you're logged in and the chat interface is visible.")
        return False


def read_prompts_from_csv(csv_path: str) -> list[dict]:
    """
    Read prompts from CSV file.

    Args:
        csv_path: Path to CSV file with columns: id, prompt

    Returns:
        List of dictionaries with 'id' and 'prompt' keys
    """
    prompts = []

    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                prompts.append({
                    'id': row['id'],
                    'prompt': row['prompt']
                })
        print(f"✓ Loaded {len(prompts)} prompts from {csv_path}")
        return prompts
    except FileNotFoundError:
        print(f"✗ Error: File {csv_path} not found")
        return []
    except Exception as e:
        print(f"✗ Error reading CSV: {e}")
        return []


def chatgpt_automation(prompt: str, prompt_id: str, run_number: int, output_file: str, page=None, browser_context=None, skip_login_modal=False):
    """
    Automates ChatGPT interaction:
    1. Opens chatgpt.com in Chromium (no login required) or uses existing page
    2. Sends a prompt
    3. Scrapes the response
    4. Saves to JSON

    Args:
        prompt: The prompt text to send
        prompt_id: ID of the prompt from CSV
        run_number: Current run number
        output_file: Path to output JSON file
        page: Existing Playwright page object (optional)
        browser_context: Tuple of (browser, context) for reuse (optional)
        skip_login_modal: If True, skip automatic "Stay logged out" handling (optional)

    Returns:
        Tuple of (browser, context, page) for potential reuse
    """
    own_browser = False

    # If no browser context provided, create new one
    if browser_context is None:
        own_browser = True
        p = sync_playwright().start()
        print("Launching browser...")

        # Launch with args to avoid bot detection
        launch_args = [
            '--disable-blink-features=AutomationControlled',  # Hide automation
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
        ]

        browser = p.chromium.launch(
            headless=False,
            args=launch_args
        )
        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
    else:
        browser, context = browser_context

    # Create new page for fresh conversation
    if page is None:
        page = context.new_page()

        # Remove webdriver flag
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

    print("Navigating to ChatGPT...")
    try:
        page.goto("https://chatgpt.com/", timeout=60000)
    except Exception as e:
        print(f"✗ Failed to navigate: {e}")
        if own_browser:
            browser.close()
        return None

    # Wait for page to load
    try:
        page.wait_for_load_state("domcontentloaded")
        print(f"✓ Page loaded. Current URL: {page.url}")
    except Exception as e:
        print(f"Warning: Page load state error: {e}")

    # Debug: Check if page is still open
    if page.is_closed():
        print("✗ Page was closed unexpectedly")
        if own_browser:
            browser.close()
        return None

    # Handle login modal if it appears (skip if using manual login)
    if not skip_login_modal:
        handle_login_modal(page)

    # Wait for and locate the prompt input textarea
    print("Waiting for chat interface...")

    # ChatGPT's main textarea typically has id="prompt-textarea"
    textarea = page.locator("#prompt-textarea")
    try:
        textarea.wait_for(timeout=30000)
        print("✓ Chat interface ready!")
    except Exception as e:
        print(f"✗ Failed to find chat interface: {e}")
        print(f"Current URL: {page.url}")
        if own_browser:
            browser.close()
        return None

    print(f"\nEntering prompt: {prompt}")
    textarea.fill(prompt)

    # Submit the prompt (press Enter or click send button)
    textarea.press("Enter")

    print("Waiting for response to start...")
    # Wait for the response to appear
    page.wait_for_timeout(2000)

    # Try multiple selectors to find the assistant's response
    print("Looking for assistant response...")

    # Wait for generation to complete by checking for stop button disappearance
    try:
        # Wait for stop button to disappear (generation complete)
        stop_button = page.locator('button[aria-label*="Stop"]')
        if stop_button.count() > 0:
            print("Waiting for response generation to complete...")
            stop_button.wait_for(state="hidden", timeout=60000)
    except:
        print("Stop button not found or already hidden, continuing...")

    page.wait_for_timeout(2000)  # Extra wait to ensure content is rendered

    print("\nScraping response...")
    response_text = None

    # Try different selectors for ChatGPT response
    selectors = [
        '[data-message-author-role="assistant"] .markdown',  # More specific
        '[data-message-author-role="assistant"]',
        'article[data-testid*="conversation-turn"] .markdown',
        'article[data-testid*="conversation-turn"]',
        '.markdown',
        '[class*="agent-turn"]',
        'div[class*="markdown"]',
    ]

    for selector in selectors:
        try:
            messages = page.locator(selector).all()
            print(f"  Trying '{selector}': found {len(messages)} elements")
            if messages and len(messages) > 0:
                # Get the last message
                response_text = messages[-1].inner_text()
                if response_text and len(response_text) > 50:  # Reasonable length for actual response
                    print(f"  ✓ Response found using: {selector}")
                    print(f"  Response length: {len(response_text)} characters")
                    break
                elif response_text:
                    print(f"    (Found but too short: {len(response_text)} chars)")
        except Exception as e:
            print(f"  Error with '{selector}': {e}")
            continue

    # Fallback: Get all text from page and extract response
    if not response_text:
        print("  Trying fallback method: extracting from full page text...")
        try:
            full_text = page.locator("body").inner_text()

            # Try to extract response after our prompt
            lines = full_text.split("\n")
            prompt_found = False
            response_lines = []

            for i, line in enumerate(lines):
                if prompt in line and not prompt_found:
                    prompt_found = True
                    continue
                if prompt_found and line.strip():
                    # Collect lines until we hit UI elements or next prompt
                    if any(x in line.lower() for x in ["regenerate", "copy code", "chatgpt can make"]):
                        break
                    response_lines.append(line.strip())
                    if len(response_lines) > 50:  # Reasonable limit
                        break

            if response_lines:
                response_text = "\n".join(response_lines)
                print(f"  ✓ Response extracted from page text ({len(response_text)} chars)")
        except Exception as e:
            print(f"  Fallback method failed: {e}")

    if not response_text:
        response_text = "No response found"
        print("\n⚠ Warning: Could not find response with any method")

    # Extract sources if present
    sources = extract_sources(page)

    # Save to JSON
    save_to_json(prompt_id, prompt, run_number, response_text, sources, output_file)

    print("✓ Response saved")

    # Return browser context for potential reuse
    return (browser, context, page)


def extract_sources(page):
    """
    Extract cited sources from ChatGPT response by clicking the "Джерела"/"Sources" button.

    Args:
        page: Playwright page object

    Returns:
        List of source dictionaries with 'number', 'name', 'title', 'url' keys
    """
    sources = []

    try:
        print("\nExtracting sources...")

        # Step 1: Find the sources button (try both Ukrainian "Джерела" and English "Sources")
        sources_button = None

        # Try Ukrainian "Джерела"
        try:
            sources_button = page.get_by_role("button", name="Джерела")
            if sources_button.count() == 0:
                sources_button = None
            else:
                print("  Found sources button: 'Джерела' (Ukrainian)")
        except:
            pass

        # Try English "Sources"
        if not sources_button:
            try:
                sources_button = page.get_by_role("button", name="Sources")
                if sources_button.count() == 0:
                    sources_button = None
                else:
                    print("  Found sources button: 'Sources' (English)")
            except:
                pass

        # Additional fallback: text-based search
        if not sources_button:
            try:
                sources_button = page.locator('button:has-text("Джерела"), button:has-text("Sources")').last
                if sources_button.count() > 0:
                    print("  Found sources button using text search")
                else:
                    sources_button = None
            except:
                pass

        if not sources_button or sources_button.count() == 0:
            print("  No sources button found - response may not have cited sources")
            return sources

        # Step 2: Count asides BEFORE clicking (to detect new panel)
        asides_before_count = page.locator('aside').count()
        print(f"  Asides before click: {asides_before_count}")

        # Step 3: Click the sources button to open sidebar
        print("  Clicking sources button to open sidebar...")
        sources_button.click()
        page.wait_for_timeout(3000)  # Wait longer for panel to fully render (increased to 3 seconds)

        # Search for citations container using STRUCTURAL markers
        print("  Searching for citations container by structure...")
        try:
            citations_container = None

            # Strategy 1: Find by specific CSS classes that ChatGPT uses for citations panel
            print("    Strategy 1: Looking for citations panel by CSS classes...")
            try:
                # The citations container has these specific classes
                potential_containers = page.locator('div.bg-token-bg-primary.flex.w-full.flex-col').all()
                for container in potential_containers:
                    text = container.inner_text()
                    # Check if it has citation header text
                    if "Цитати" in text or "Citations" in text or "Джерела" in text or "Цитування" in text:
                        # Verify it has multiple links
                        links_count = container.locator('a[target="_blank"][href^="http"]').count()
                        if links_count >= 2:
                            citations_container = container
                            print(f"    ✓ Found citations container by CSS classes ({links_count} links)")
                            break
            except Exception as e:
                print(f"    Strategy 1 failed: {e}")

            # Strategy 2: Find container with citation header AND multiple external links
            if not citations_container:
                print("    Strategy 2: Looking for container with citation header + links...")
                try:
                    all_divs = page.locator('div').all()
                    for idx, div in enumerate(all_divs):
                        try:
                            text = div.inner_text()
                            # Check if it has citation section header
                            has_citation_header = ("Цитати" in text or "Citations" in text or
                                                  "Джерела" in text or "Цитування" in text)

                            if has_citation_header:
                                # Count external links with target="_blank"
                                links_count = div.locator('a[target="_blank"][href^="http"]').count()
                                if links_count >= 2:
                                    citations_container = div
                                    print(f"    ✓ Found citations container by structure ({links_count} links)")
                                    break
                        except:
                            continue
                except Exception as e:
                    print(f"    Strategy 2 failed: {e}")

            # Strategy 3: Find by UL element with specific classes
            if not citations_container:
                print("    Strategy 3: Looking for <ul> with citation structure...")
                try:
                    ul_elements = page.locator('ul.flex.flex-col').all()
                    for ul in ul_elements:
                        links_count = ul.locator('a[href^="http"][target="_blank"]').count()
                        if links_count >= 2:
                            # Get parent container (go up 2 levels)
                            citations_container = ul.locator('xpath=../..').first
                            print(f"    ✓ Found citations container by <ul> structure ({links_count} links)")
                            break
                except Exception as e:
                    print(f"    Strategy 3 failed: {e}")

            if citations_container:
                print(f"  ✓ FOUND CITATIONS CONTAINER using structural markers!")
                panel = citations_container
                print(f"  ✓ Panel variable set to found citations container")
            else:
                print("  ✗ No citations container found using structural markers")

        except Exception as e:
            print(f"  Error searching for citations container: {e}")

        # Step 4: Find Citations panel (skip if brute-force already found it)
        if not panel:
            # Only run aside detection if brute-force didn't find citations
            try:
                page.wait_for_function(
                    f'document.querySelectorAll("aside").length > {asides_before_count}',
                    timeout=5000
                )
                print("  ✓ New aside appeared after clicking")
            except:
                print("  ⚠ No new aside detected, will search existing ones")

            # Step 5: Find the CORRECT Citations panel (not the left navigation sidebar)
            asides = page.locator('aside').all()
            print(f"  Total asides now: {len(asides)}")

            panel = None
            for idx, aside in enumerate(asides):
                try:
                    # Get position to check if it's on the right side of screen
                    box = aside.bounding_box()
                    text = aside.inner_text()

                    # Skip if it's the left navigation sidebar
                    if "New chat" in text or "Library" in text:
                        print(f"  Skipping aside #{idx+1}: Left navigation sidebar")
                        continue

                    # Check for navigation-specific elements in HTML
                    try:
                        html = aside.inner_html()
                        if "create-new-chat-button" in html or "sidebar-item-library" in html:
                            print(f"  Skipping aside #{idx+1}: Navigation sidebar (by HTML)")
                            continue
                    except:
                        pass

                    # Check if this aside is on the right side of screen
                    if box:
                        print(f"  Checking aside #{idx+1} at position x={box['x']}, y={box['y']}")

                        # Citations panel should be on the right (x > 600 typically)
                        if box['x'] > 600:
                            # Verify it has citation-like content
                            if len(text) > 50:
                                print(f"    Text length: {len(text)} chars")
                                print(f"    Text preview: {text[:100]}...")

                                # Check for citation indicators
                                has_citations = (
                                    "Citations" in text or
                                    "Цитування" in text or
                                    "http" in text or
                                    len(text) > 100  # Citations panel has substantial content
                                )

                                if has_citations:
                                    panel = aside
                                    print(f"  ✓ Found Citations panel (aside #{idx+1}) at x={box['x']}")
                                    break
                                else:
                                    print(f"    Doesn't look like Citations panel")
                        else:
                            print(f"    Too far left (x={box['x']}), skipping")

                except Exception as e:
                    print(f"  Error checking aside #{idx+1}: {e}")
                    continue

            # Fallback: if no panel found, try the last aside (newest)
            if not panel and len(asides) > 0:
                print("  Trying fallback: using last aside")
                panel = asides[-1]
                try:
                    text_check = panel.inner_text()
                    if "New chat" not in text_check:
                        print("  ✓ Fallback succeeded (last aside is not navigation)")
                    else:
                        panel = None
                        print("  ✗ Fallback failed (last aside is still navigation)")
                except:
                    pass
        else:
            print("  ✓ Using citations container from brute-force search")

        if not panel:
            print("  ✗ Could not find Citations panel after clicking button")
            # Try to close anything that might have opened
            try:
                page.keyboard.press("Escape")
            except:
                pass
            return sources

        # Wait for panel content to load
        try:
            print("  Waiting for panel content to load...")
            # Try to wait for at least one link to appear
            panel.locator('a').first.wait_for(state="visible", timeout=5000)
            print("  ✓ Panel content loaded")
        except Exception as e:
            print(f"  Warning: Could not detect links loading: {e}")
            # Give it extra time anyway
            page.wait_for_timeout(2000)

        # Step 4: Verify panel content and add comprehensive debugging
        print("  Verifying panel content...")

        # Get panel text for verification
        panel_text = ""
        try:
            panel_text = panel.inner_text()
            print(f"  Panel text length: {len(panel_text)} chars")
            if len(panel_text) > 0:
                print(f"  Panel text preview: {panel_text[:200]}...")
        except Exception as e:
            print(f"  Could not get panel text: {e}")

        # Verify we have the Citations panel
        if panel_text and len(panel_text) > 50:
            if "Citations" in panel_text or "Цитування" in panel_text or "Джерела" in panel_text:
                print("  ✓ Confirmed this is the Citations panel")
            else:
                print("  ⚠ Warning: Panel may not be Citations panel")
                # Try to find actual Citations panel
                try:
                    citations_panel = page.locator('aside:has-text("Citations"), aside:has-text("Цитування")').first
                    if citations_panel.count() > 0 and citations_panel.is_visible():
                        panel = citations_panel
                        panel_text = panel.inner_text()
                        print("  ✓ Found correct Citations panel")
                except:
                    pass
        else:
            print("  ⚠ Warning: Panel text is empty or very short")

        print("  Extracting sources from panel...")

        # Try multiple selector strategies
        source_links = []

        # Strategy 0: Direct extraction from known ul > li > a structure
        if panel:
            try:
                citation_links = panel.locator('ul > li > a[href^="http"]').all()

                # If primary fails, try alternatives
                if len(citation_links) == 0:
                    citation_links = panel.locator('a[target="_blank"]').all()

                if len(citation_links) == 0:
                    citation_links = panel.locator('a[href*="utm_source=chatgpt"]').all()

                if len(citation_links) == 0:
                    citation_links = panel.locator('ul a[href^="http"]').all()

                if len(citation_links) > 0:
                    print(f"    ✓ Found {len(citation_links)} citation links in ul > li > a structure")

                    for idx, link in enumerate(citation_links, 1):
                        try:
                            url = link.get_attribute('href') or ""

                            # Get all divs - they contain name, title, description
                            divs = link.locator('div').all()
                            text_parts = []

                            for div in divs:
                                try:
                                    text = div.inner_text().strip()
                                    # Skip empty text and favicon URLs
                                    if text and not text.startswith('http') and len(text) > 1:
                                        text_parts.append(text)
                                except:
                                    continue

                            # Extract components
                            # First div typically has store name
                            # Second div has title
                            # Third div has description
                            name = text_parts[0] if len(text_parts) > 0 else f"Source {idx}"
                            title = text_parts[1] if len(text_parts) > 1 else ""
                            description = text_parts[2] if len(text_parts) > 2 else ""

                            sources.append({
                                'number': idx,
                                'name': name,
                                'title': title,
                                'description': description,
                                'url': url
                            })

                            print(f"      ✓ [{idx}] {name} - {url}")

                        except Exception as e:
                            print(f"      ✗ Error extracting citation {idx}: {e}")

                    # If we got sources, skip other strategies
                    if len(sources) > 0:
                        print(f"  ✓ Strategy 0 succeeded! Extracted {len(sources)} sources")
                        source_links = []  # Clear to skip other strategies
                else:
                    print("    No citation links found with ul > li > a structure")

            except Exception as e:
                print(f"  Strategy 0 error: {e}")

        # Strategy 1: Try href starting with http
        try:
            source_links = panel.locator('a[href^="http"]').all()
            print(f"  Strategy 1 (a[href^='http']): found {len(source_links)} links")
        except Exception as e:
            print(f"  Strategy 1 error: {e}")

        # Strategy 2: Try any href
        if len(source_links) == 0:
            try:
                source_links = panel.locator('a[href]').all()
                print(f"  Strategy 2 (a[href]): found {len(source_links)} links")
            except Exception as e:
                print(f"  Strategy 2 error: {e}")

        # Strategy 3: Try all links
        if len(source_links) == 0:
            try:
                source_links = panel.locator('a').all()
                print(f"  Strategy 3 (all <a> tags): found {len(source_links)} links")
            except Exception as e:
                print(f"  Strategy 3 error: {e}")

        # Strategy 4: Look in list items
        if len(source_links) == 0:
            try:
                source_links = panel.locator('li a, [role="listitem"] a').all()
                print(f"  Strategy 4 (list item links): found {len(source_links)} links")
            except Exception as e:
                print(f"  Strategy 4 error: {e}")

        # Strategy 5: Look for any clickable/link-like elements
        if len(source_links) == 0:
            try:
                source_links = panel.locator('[href], [role="link"]').all()
                print(f"  Strategy 5 (href or role=link): found {len(source_links)} links")
            except Exception as e:
                print(f"  Strategy 5 error: {e}")

        # Strategy 6: Look for citation-specific structures
        if len(source_links) == 0:
            try:
                source_links = panel.locator('[data-testid*="citation"], [class*="citation"]').all()
                print(f"  Strategy 6 (citation elements): found {len(source_links)} links")
            except Exception as e:
                print(f"  Strategy 6 error: {e}")

        # Strategy 7: Try finding divs with links inside
        if len(source_links) == 0:
            try:
                # Find parent containers that might hold citation info
                citation_containers = panel.locator('div[class] > a').all()
                if len(citation_containers) > 0:
                    source_links = citation_containers
                    print(f"  Strategy 7 (div > a): found {len(source_links)} links")
            except Exception as e:
                print(f"  Strategy 7 error: {e}")

        # Strategy 8: Get ALL clickable elements and filter later
        if len(source_links) == 0:
            try:
                all_clickable = panel.locator('a, button, [onclick], [role="button"]').all()
                # Filter for ones that look like citations (have meaningful text)
                source_links = [el for el in all_clickable if len(el.inner_text().strip()) > 3]
                print(f"  Strategy 8 (all clickable, filtered): found {len(source_links)} elements")
            except Exception as e:
                print(f"  Strategy 8 error: {e}")

        # Strategy 9: Manual text parsing as last resort
        if len(source_links) == 0:
            print("  Strategy 9: Attempting manual text parsing")
            try:
                import re
                panel_full_text = panel.inner_text()

                # Look for URL patterns in text
                urls = re.findall(r'https?://[^\s\)]+', panel_full_text)
                print(f"  Found {len(urls)} URLs in panel text via regex")

                # Parse structured citation entries
                # Citations panel typically has format:
                # [Icon] Name
                # Title/Description text
                # URL

                lines = panel_full_text.split('\n')
                current_citation = {}
                citations_parsed = []

                for i, line in enumerate(lines):
                    line = line.strip()
                    if not line:
                        # Empty line might separate citations
                        if current_citation and 'name' in current_citation:
                            citations_parsed.append(current_citation)
                            current_citation = {}
                        continue

                    # Check if line contains a URL
                    if 'http' in line:
                        url_match = re.search(r'https?://[^\s\)]+', line)
                        if url_match:
                            if 'url' not in current_citation:
                                current_citation['url'] = url_match.group()
                            # Line might also contain description
                            text_without_url = line.replace(url_match.group(), '').strip()
                            if text_without_url:
                                if 'description' not in current_citation:
                                    current_citation['description'] = text_without_url
                                else:
                                    current_citation['description'] += ' ' + text_without_url
                    else:
                        # Line doesn't contain URL
                        # Short lines are likely names (Allo, comfy.ua, Citrus, etc.)
                        if len(line) < 50 and 'name' not in current_citation:
                            current_citation['name'] = line
                        else:
                            # Longer lines are descriptions
                            if 'description' not in current_citation:
                                current_citation['description'] = line
                            else:
                                current_citation['description'] += ' ' + line

                # Add last citation if exists
                if current_citation and 'name' in current_citation:
                    citations_parsed.append(current_citation)

                print(f"  Parsed {len(citations_parsed)} structured citations from text")

                # Create source entries from parsed citations
                for idx, citation in enumerate(citations_parsed, 1):
                    name = citation.get('name', f'Source {idx}')
                    description = citation.get('description', '')
                    url = citation.get('url', '')

                    sources.append({
                        'number': idx,
                        'name': name,
                        'title': description[:200] if description else name,  # Limit title length
                        'url': url if url else 'No URL found'
                    })
                    print(f"    ✓ [{idx}] {name} - {url if url else 'No URL'}")

                # Fallback: if structured parsing didn't work, use URL-based extraction
                if len(sources) == 0 and len(urls) > 0:
                    print("  Falling back to URL-based extraction...")
                    for idx, url in enumerate(urls, 1):
                        # Try to extract name from text near URL
                        name = f"Source {idx}"

                        url_pos = panel_full_text.find(url)
                        if url_pos > 0:
                            text_before = panel_full_text[max(0, url_pos-150):url_pos].strip()
                            text_lines = text_before.split('\n')
                            if text_lines:
                                potential_name = text_lines[-1].strip()
                                if potential_name and len(potential_name) < 100:
                                    name = potential_name

                        sources.append({
                            'number': idx,
                            'name': name,
                            'title': name,
                            'url': url
                        })
                        print(f"    ✓ [{idx}] {name} - {url}")

                # If we found sources via text parsing, skip link processing
                if len(sources) > 0:
                    source_links = []

            except Exception as e:
                print(f"  Manual parsing failed: {e}")

        # Process found links (if any)
        if len(source_links) > 0:
            print(f"  Processing {len(source_links)} links...")
            for idx, link in enumerate(source_links, 1):
                try:
                    url = link.get_attribute('href') or ""

                    # Handle relative URLs
                    if url and not url.startswith('http'):
                        if url.startswith('/'):
                            url = f"https://chatgpt.com{url}"

                    text = link.inner_text().strip()

                    # Extract name (usually first line)
                    lines = text.split('\n')
                    name = lines[0] if lines else text[:100]

                    # Clean up name if it's too long
                    if len(name) > 100:
                        name = name[:97] + "..."

                    source_data = {
                        'number': idx,
                        'name': name,
                        'title': text,
                        'url': url
                    }

                    sources.append(source_data)
                    print(f"    ✓ [{idx}] {name} - {url}")

                except Exception as e:
                    print(f"    ✗ Error extracting source {idx}: {e}")
                    continue

        # Step 5: Close the panel
        try:
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)
            print("  Panel closed")
        except:
            pass

        if sources:
            print(f"  ✓ Successfully extracted {len(sources)} sources")
        else:
            print("  ⚠ No sources were extracted from panel")

    except Exception as e:
        print(f"  ✗ Error during source extraction: {e}")
        # Make sure to close any open panels
        try:
            page.keyboard.press("Escape")
        except:
            pass

    return sources


def start_new_conversation(page, skip_login_modal=False):
    """
    Start a new conversation by navigating to fresh ChatGPT page.

    Args:
        page: Playwright page object
        skip_login_modal: If True, skip automatic "Stay logged out" handling (optional)

    Returns:
        True if successful, False otherwise
    """
    print("\nStarting new conversation...")
    try:
        # Navigate to base URL to start fresh conversation
        page.goto("https://chatgpt.com/", timeout=60000)
        page.wait_for_load_state("domcontentloaded")

        # Handle login modal if it appears (skip if using manual login)
        if not skip_login_modal:
            handle_login_modal(page)

        # Wait for textarea to be ready
        textarea = page.locator("#prompt-textarea")
        textarea.wait_for(timeout=30000)

        print("✓ New conversation ready")
        return True
    except Exception as e:
        print(f"✗ Failed to start new conversation: {e}")
        return False


def save_to_json(prompt_id: str, prompt_text: str, run_number: int, response_text: str, sources: list, output_file: str):
    """Save prompt and response to JSON file with nested structure.

    Structure: [{"prompt_id": "1", "prompt": "...", "answers": [{"run_number": 1, "response": "...", "citations": [{"url": "", "text": ""}], "timestamp": "..."}]}]
    """
    import json

    timestamp = datetime.now().isoformat()

    # Load existing data
    data = []
    if os.path.exists(output_file):
        try:
            with open(output_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, IOError):
            # If file is corrupted or empty, start fresh
            data = []

    # Format citations as list of {url, text} objects
    citations = []
    if sources and len(sources) > 0:
        for source in sources:
            # Combine name, title, description into text
            text_parts = []
            if source.get('name'):
                text_parts.append(source['name'])
            if source.get('title') and source['title'] != source.get('name'):
                text_parts.append(source['title'])
            if source.get('description') and source['description'] != source.get('title'):
                text_parts.append(source['description'])

            citation_text = ' - '.join(text_parts) if text_parts else source.get('name', 'Unknown')

            citations.append({
                'url': source.get('url', ''),
                'text': citation_text
            })

    # Find or create prompt entry
    prompt_entry = None
    for entry in data:
        if entry.get('prompt_id') == prompt_id:
            prompt_entry = entry
            break

    if not prompt_entry:
        prompt_entry = {
            'prompt_id': prompt_id,
            'prompt': prompt_text,
            'answers': []
        }
        data.append(prompt_entry)

    # Append answer to prompt
    prompt_entry['answers'].append({
        'run_number': run_number,
        'response': response_text,
        'citations': citations,
        'timestamp': timestamp
    })

    # Save back to file
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"✓ Results saved to {output_file}")



def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Automate ChatGPT interactions with prompts from CSV file"
    )
    parser.add_argument(
        "-i", "--input",
        default="prompts.csv",
        help="Path to input CSV file with prompts (default: prompts.csv)"
    )
    parser.add_argument(
        "-r", "--runs",
        type=int,
        default=1,
        help="Number of runs per prompt in fresh conversations (default: 1)"
    )
    parser.add_argument(
        "-o", "--output",
        default="chatgpt_results.json",
        help="Path to output file (default: chatgpt_results.json)"
    )
    parser.add_argument(
        "--wait-for-login",
        action="store_true",
        help="Pause before automation to allow manual login (enables cited sources)"
    )
    parser.add_argument(
        "-s", "--session-file",
        default="chatgpt_session.json",
        help="Path to session file for persisting login state (default: chatgpt_session.json)"
    )
    return parser.parse_args()


def main():
    """Main function to orchestrate CSV processing and multiple runs."""
    args = parse_args()

    print(f"=== ChatGPT Automation ===")
    print(f"Input file: {args.input}")
    print(f"Runs per prompt: {args.runs}")
    print(f"Output file: {args.output}")
    print(f"Session file: {args.session_file}")
    print()

    # Read prompts from CSV
    prompts = read_prompts_from_csv(args.input)
    if not prompts:
        print("✗ No prompts found. Exiting.")
        return

    total_prompts = len(prompts)
    total_runs = total_prompts * args.runs

    print(f"Total prompts: {total_prompts}")
    print(f"Total runs: {total_runs}")
    print()

    # Process each prompt
    browser_context = None
    page = None
    completed_runs = 0
    session_loaded = False

    # Try to load existing session
    print("Checking for existing session...")
    if os.path.exists(args.session_file):
        print(f"✓ Found session file: {args.session_file}")
        print("Attempting to load saved session...")

        # Launch browser with saved session
        p = sync_playwright().start()
        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
        ]
        browser = p.chromium.launch(headless=False, args=launch_args)

        # Load session into context
        try:
            context = browser.new_context(
                storage_state=args.session_file,
                viewport={'width': 1280, 'height': 720},
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            page = context.new_page()

            # Remove webdriver flag
            page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # Validate session
            if is_logged_in(page):
                browser_context = (browser, context)
                session_loaded = True
                print("✓ Session loaded and validated successfully!\n")
            else:
                print("⚠ Session expired or invalid, will need to login again")
                page.close()
                browser.close()
                page = None
                browser_context = None
        except Exception as e:
            print(f"✗ Failed to load session: {e}")
            if page:
                page.close()
            if browser:
                browser.close()
            page = None
            browser_context = None
    else:
        print(f"⚠ No session file found at {args.session_file}")

    # Handle manual login if session not loaded and login requested
    if not session_loaded and args.wait_for_login:
        print("\nManual login mode enabled")
        print("Opening browser for login...")

        # Launch browser
        p = sync_playwright().start()
        launch_args = [
            '--disable-blink-features=AutomationControlled',
            '--disable-dev-shm-usage',
            '--no-sandbox',
            '--disable-setuid-sandbox',
        ]
        browser = p.chromium.launch(headless=False, args=launch_args)
        context = browser.new_context(
            viewport={'width': 1280, 'height': 720},
            user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        )
        page = context.new_page()

        # Remove webdriver flag
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });
        """)

        # Navigate and wait for login
        page.goto("https://chatgpt.com/", timeout=60000)
        page.wait_for_load_state("domcontentloaded")

        # Wait for manual login
        if not wait_for_manual_login(page):
            print("✗ Manual login failed or was cancelled")
            browser.close()
            return

        # Store browser context
        browser_context = (browser, context)

        # Save session for future use
        print(f"\nSaving session to {args.session_file}...")
        save_session(context, args.session_file)

        print("✓ Manual login successful, continuing with automation...\n")
    elif not session_loaded and not args.wait_for_login:
        print("\n⚠ No valid session found and --wait-for-login not specified")
        print("   Either:")
        print("   1. Use --wait-for-login flag to perform manual login, or")
        print("   2. Provide a valid session file with -s/--session-file")
        return

    try:
        for prompt_idx, prompt_data in enumerate(prompts, 1):
            prompt_id = prompt_data['id']
            prompt_text = prompt_data['prompt']

            print(f"\n{'='*60}")
            print(f"Prompt {prompt_idx}/{total_prompts} (ID: {prompt_id})")
            print(f"Text: {prompt_text}")
            print(f"{'='*60}")

            # Run N times for this prompt
            for run in range(1, args.runs + 1):
                completed_runs += 1
                print(f"\n--- Run {run}/{args.runs} (Overall: {completed_runs}/{total_runs}) ---")

                # For runs after the first, start a new conversation
                if browser_context and page and run > 1:
                    if not start_new_conversation(page, skip_login_modal=args.wait_for_login):
                        print("⚠ Failed to start new conversation, creating fresh browser...")
                        if browser_context:
                            browser, context = browser_context
                            browser.close()
                        browser_context = None
                        page = None

                # Execute automation
                try:
                    result = chatgpt_automation(
                        prompt=prompt_text,
                        prompt_id=prompt_id,
                        run_number=run,
                        output_file=args.output,
                        page=page,
                        browser_context=browser_context,
                        skip_login_modal=args.wait_for_login
                    )

                    if result:
                        browser_context = (result[0], result[1])
                        page = result[2]
                    else:
                        print("⚠ Run failed, resetting browser...")
                        browser_context = None
                        page = None

                except Exception as e:
                    print(f"✗ Error during run: {e}")
                    # Reset browser context on error
                    if browser_context:
                        try:
                            browser, context = browser_context
                            browser.close()
                        except:
                            pass
                    browser_context = None
                    page = None

    finally:
        # Clean up browser
        if browser_context:
            try:
                print("\nClosing browser...")
                browser, context = browser_context
                browser.close()
            except Exception as e:
                print(f"Warning: Error closing browser: {e}")

    print(f"\n{'='*60}")
    print(f"✓ Completed {completed_runs}/{total_runs} runs")
    print(f"✓ Results saved to {args.output}")
    print("Done!")


if __name__ == "__main__":
    main()
