"""
ChatGPT Session Creator

This script opens a browser, allows you to manually log in to ChatGPT,
and saves the authenticated session to a file for later reuse.

Usage:
    uv run create_session.py
    uv run create_session.py --output my_session.json
    uv run create_session.py --output session_account1.json

This allows creating multiple sessions for different Google accounts
to avoid rate limits when running the main automation script.
"""

import argparse
import os
from playwright.sync_api import sync_playwright

# Import helper functions from bot.py
from src.bot import (
    handle_welcome_back_modal,
    save_session,
    wait_for_manual_login
)


def create_session(output_file: str):
    """
    Open browser, wait for manual login, and save session to file.

    Args:
        output_file: Path to save the session file

    Returns:
        True if successful, False otherwise
    """
    print("="*60)
    print("ChatGPT Session Creator")
    print("="*60)
    print(f"Session will be saved to: {output_file}")
    print()

    # Check if session file already exists
    if os.path.exists(output_file):
        print(f"⚠ Warning: Session file already exists: {output_file}")
        response = input("Do you want to overwrite it? (y/N): ")
        if response.lower() != 'y':
            print("Cancelled.")
            return False
        print()

    # Launch Playwright
    print("Launching browser...")
    p = sync_playwright().start()

    # Launch browser arguments (same as main.py)
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
        print("✓ Page loaded")
        print()

        # Wait for manual login
        if not wait_for_manual_login(page):
            print("✗ Login failed or was cancelled")
            browser.close()
            p.stop()
            return False

        # Handle "Welcome back" modal if it appears
        print("\nChecking for 'Welcome back' modal...")
        handle_welcome_back_modal(page)

        # Verify chat interface is ready
        print("Verifying chat interface is ready...")
        try:
            textarea = page.locator("#prompt-textarea")
            textarea.wait_for(timeout=10000, state="visible")
            print("✓ Chat interface is ready")
        except Exception as e:
            print(f"✗ Failed to verify chat interface: {e}")
            browser.close()
            p.stop()
            return False

        # Save session to file
        print()
        print(f"Saving session to {output_file}...")
        if save_session(context, output_file):
            print()
            print("="*60)
            print("✓ SUCCESS!")
            print("="*60)
            print(f"Session saved to: {output_file}")
            print()
            print("You can now use this session file with the main script:")
            print(f"  uv run main.py --session-file {output_file} --input prompts.csv")
            print("="*60)
            success = True
        else:
            print("✗ Failed to save session")
            success = False

    except Exception as e:
        print(f"✗ Error: {e}")
        success = False

    finally:
        # Close browser
        print("\nClosing browser...")
        browser.close()
        p.stop()

    return success


def parse_args():
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Create a ChatGPT session file by manually logging in",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Create default session file
  uv run create_session.py

  # Create named session for different accounts
  uv run create_session.py --output session_account1.json
  uv run create_session.py --output session_account2.json
  uv run create_session.py --output session_google_work.json
  uv run create_session.py --output session_google_personal.json

  # Then use with main script
  uv run main.py --session-file session_account1.json --input prompts.csv --runs 10
  uv run main.py --session-file session_account2.json --input prompts.csv --runs 10
        """
    )
    parser.add_argument(
        "-o", "--output",
        default="session.json",
        help="Path to output session file (default: session.json)"
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    print()
    success = create_session(args.output)
    print()

    if success:
        print("✓ Session creation completed successfully!")
        return 0
    else:
        print("✗ Session creation failed")
        return 1


if __name__ == "__main__":
    exit(main())
