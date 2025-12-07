"""
ChatGPT Session Creator

Standalone utility script for creating authenticated session files.
Run this manually to create sessions for different accounts.

Usage:
    uv run scripts/create_session.py --output sessions/account1.json
    uv run scripts/create_session.py --output sessions/account2.json

This script is NOT part of the main application - it's a utility
for manually creating session files that the bot will use.
"""

import argparse
import time
from pathlib import Path

from playwright.sync_api import sync_playwright


def wait_for_manual_login(page, timeout: int = 600) -> bool:
    """
    Wait for user to manually log in to ChatGPT.

    Args:
        page: Playwright page object
        timeout: Maximum wait time in seconds (default: 10 minutes)

    Returns:
        True if login successful, False otherwise
    """
    print("=" * 60)
    print("MANUAL LOGIN REQUIRED")
    print("=" * 60)
    print("Please log in to ChatGPT in the browser window.")
    print("The script will continue automatically once you're logged in.")
    print()
    print("Waiting for you to complete login...")
    print(f"(You have up to {timeout // 60} minutes to complete the login)")
    print("=" * 60)
    print()

    start_time = time.time()
    check_interval = 2

    while time.time() - start_time < timeout:
        # Strategy 1: Check if chat interface is ready
        try:
            textarea = page.locator("#prompt-textarea")
            if textarea.count() > 0 and textarea.is_visible(timeout=1000):
                print("Login successful! Chat interface detected.")
                return True
        except Exception:
            pass

        # Strategy 2: Check if "Log in" button is absent
        try:
            login_button = page.locator('button:has-text("Log in"), a:has-text("Log in")').first
            if login_button.count() == 0:
                print("Login detected (no login button present)")
                page.wait_for_timeout(3000)

                textarea = page.locator("#prompt-textarea")
                if textarea.count() > 0:
                    print("Chat interface ready")
                    return True
                else:
                    print("Chat interface not ready yet, continuing to wait...")
        except Exception:
            pass

        # Strategy 3: Check for user avatar/profile
        try:
            avatar_selectors = [
                '[data-testid="profile-button"]',
                'button[aria-label*="User"]',
                'img[alt*="User"]',
                '[role="button"] img'
            ]
            for selector in avatar_selectors:
                avatar = page.locator(selector).first
                if avatar.count() > 0 and avatar.is_visible(timeout=1000):
                    print("Login detected (user profile visible)")
                    page.wait_for_timeout(3000)

                    textarea = page.locator("#prompt-textarea")
                    if textarea.count() > 0:
                        print("Chat interface ready")
                        return True
                    else:
                        print("Chat interface not ready yet, continuing to wait...")
                    break
        except Exception:
            pass

        # Show progress
        elapsed = int(time.time() - start_time)
        if elapsed > 0 and elapsed % 10 == 0:
            remaining = timeout - elapsed
            print(f"Still waiting... ({remaining}s remaining)")

        page.wait_for_timeout(check_interval * 1000)

    print(f"Login timeout after {timeout} seconds")
    print("The chat interface did not appear in time.")
    return False


def create_session(output_file: str) -> bool:
    """
    Open browser, wait for manual login, and save session to file.

    Args:
        output_file: Path to save the session file

    Returns:
        True if successful, False otherwise
    """
    output_path = Path(output_file)

    print("=" * 60)
    print("ChatGPT Session Creator")
    print("=" * 60)
    print(f"Session will be saved to: {output_path}")
    print()

    # Check if session file already exists
    if output_path.exists():
        print(f"Warning: Session file already exists: {output_path}")
        response = input("Do you want to overwrite it? (y/N): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return False
        print()

    # Ensure parent directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Launch Playwright
    print("Launching browser...")

    with sync_playwright() as p:
        # Launch browser with anti-detection args
        launch_args = [
            '--disable-blink-features=AutomationControlled',
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

        try:
            # Navigate to ChatGPT
            print("Navigating to ChatGPT...")
            page.goto("https://chatgpt.com/", timeout=60000)
            page.wait_for_load_state("domcontentloaded")
            print("Page loaded")
            print()

            # Wait for manual login
            if not wait_for_manual_login(page):
                print("Login failed or was cancelled")
                return False

            print("Chat interface is ready")

            # Save session to file
            print()
            print(f"Saving session to {output_path}...")
            context.storage_state(path=str(output_path))

            print()
            print("=" * 60)
            print("SUCCESS!")
            print("=" * 60)
            print(f"Session saved to: {output_path}")
            print()
            print("You can now use this session file with the main script:")
            print(f"  uv run src/bot.py --sessions-dir {output_path.parent} --input prompts.csv")
            print("=" * 60)

            return True

        except Exception as e:
            print(f"Error: {e}")
            return False

        finally:
            print("\nClosing browser...")
            browser.close()


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a ChatGPT session file by manually logging in",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create default session file
  uv run scripts/create_session.py

  # Create named session for different accounts
  uv run scripts/create_session.py --output sessions/account1.json
  uv run scripts/create_session.py --output sessions/account2.json
  uv run scripts/create_session.py --output sessions/google_work.json
  uv run scripts/create_session.py --output sessions/google_personal.json

  # Then use with main script
  uv run src/bot.py --sessions-dir sessions --input prompts.csv --max-attempts 3
        """
    )
    parser.add_argument(
        "-o", "--output",
        default="session.json",
        help="Path to output session file (default: session.json)"
    )
    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    print()
    success = create_session(args.output)
    print()

    if success:
        print("Session creation completed successfully!")
        return 0
    else:
        print("Session creation failed")
        return 1


if __name__ == "__main__":
    exit(main())
