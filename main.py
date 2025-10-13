import csv
import os
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright


def chatgpt_automation():
    """
    Automates ChatGPT interaction:
    1. Opens chatgpt.com in Chromium (no login required)
    2. Sends a prompt
    3. Scrapes the response
    4. Saves to CSV
    """
    prompt = "Порадь ноутбук до 15000 грн"

    with sync_playwright() as p:
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
            browser.close()
            return

        # Wait for page to load
        try:
            page.wait_for_load_state("domcontentloaded")
            print(f"✓ Page loaded. Current URL: {page.url}")
        except Exception as e:
            print(f"Warning: Page load state error: {e}")

        # Debug: Check if page is still open
        if page.is_closed():
            print("✗ Page was closed unexpectedly")
            browser.close()
            return

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
            print("Taking screenshot for debugging...")
            try:
                page.screenshot(path="error_screenshot.png")
                print("Screenshot saved to error_screenshot.png")
            except:
                pass
            browser.close()
            return

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

        # Take a screenshot for debugging
        page.screenshot(path="debug_screenshot.png")
        print("Screenshot saved to debug_screenshot.png")

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
                # Save full text for debugging
                with open("debug_page_text.txt", "w", encoding="utf-8") as f:
                    f.write(full_text)
                print(f"  Full page text saved to debug_page_text.txt ({len(full_text)} chars)")

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
            print("Check debug_screenshot.png and debug_page_text.txt for details")

        # Save to CSV
        save_to_csv(prompt, response_text)

        print("\nClosing browser...")
        browser.close()

    print("Done!")


def save_to_csv(input_text: str, output_text: str):
    """Save prompt and response to CSV file with timestamp."""
    csv_file = "chatgpt_results.csv"
    timestamp = datetime.now().isoformat()

    file_exists = os.path.exists(csv_file)

    with open(csv_file, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)

        # Write header if file is new
        if not file_exists:
            writer.writerow(["input", "output", "timestamp"])

        # Write data
        writer.writerow([input_text, output_text, timestamp])

    print(f"✓ Results saved to {csv_file}")


def main():
    try:
        chatgpt_automation()
    except Exception as e:
        print(f"✗ Error: {e}")
        raise


if __name__ == "__main__":
    main()
