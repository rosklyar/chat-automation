"""ChatGPT authentication handling."""

import re
from playwright.sync_api import Page


class ChatGPTAuthenticator:
    """
    Handles ChatGPT authentication flows.

    Supports:
    - "Welcome back" modals with account selection
    - "Log in or sign up" modals
    - "Continue with Google" buttons
    - Detecting already-authenticated state
    """

    def authenticate_if_needed(self, page: Page, max_attempts: int = 2) -> bool:
        """
        Handle authentication after loading ChatGPT with session.

        Algorithm:
        1. Wait for login modal to appear
        2. If modal appears -> handle it
        3. If no modal -> check for "Log in" button
        4. If "Log in" button absent -> user is logged in
        5. If "Log in" button present -> click it and retry

        Args:
            page: Playwright page object
            max_attempts: Maximum login attempts

        Returns:
            True if authenticated successfully
        """
        for attempt in range(1, max_attempts + 1):
            print(f"Authentication attempt {attempt}/{max_attempts}")

            # Wait for any modal to appear
            print("Waiting for login modal...")
            page.wait_for_timeout(5000)

            modal_type = self._detect_modal(page)

            if modal_type:
                print(f"Detected modal: {modal_type}")
                if not self._handle_modal(page, modal_type):
                    print("Failed to handle authentication modal")
                    return False

                # Wait for authentication to complete
                print("Waiting for authentication to complete...")
                page.wait_for_timeout(5000)

                if self._is_chat_interface_ready(page):
                    print("Authenticated successfully - chat interface ready")
                    return True
                else:
                    print("Chat interface not ready after authentication")
                    return False

            # No modal - check for login button
            print("No modal appeared - checking for 'Log in' button...")
            login_button = self._find_login_button(page)

            if not login_button:
                # No login button = already authenticated
                print("No 'Log in' button found - verifying authentication...")
                if self._is_chat_interface_ready(page):
                    print("Already authenticated - chat interface ready")
                    return True
                else:
                    print("Neither modal nor chat interface found")
                    return False

            # Click login button to trigger modal
            print("Found 'Log in' button - clicking to trigger modal...")
            try:
                login_button.click(timeout=5000)
                print("Clicked 'Log in' button - will retry modal detection")
            except Exception as e:
                print(f"Failed to click 'Log in' button: {e}")
                return False

        print("Authentication failed after maximum attempts")
        return False

    def _detect_modal(self, page: Page) -> str | None:
        """Detect which authentication modal is showing."""
        # Check for "Welcome back" modal
        try:
            welcome = page.locator('text="Welcome back"')
            if welcome.is_visible(timeout=1000):
                return "welcome_back"
        except Exception:
            pass

        # Check for "Log in or sign up" modal
        try:
            login_modal = page.locator('text="Log in or sign up"')
            if login_modal.is_visible(timeout=1000):
                return "log_in_sign_up"
        except Exception:
            pass

        return None

    def _handle_modal(self, page: Page, modal_type: str) -> bool:
        """Handle the detected authentication modal."""
        # Wait for modal to fully render
        page.wait_for_timeout(1500)

        auth_button = None

        # Try account button for "Welcome back"
        if modal_type == "welcome_back":
            auth_button = self._find_account_button(page)
            if auth_button:
                print("Found account selection button")

        # Fallback to "Continue with Google"
        if not auth_button:
            auth_button = self._find_google_button(page)
            if auth_button:
                print("Found 'Continue with Google' button")

        if not auth_button:
            print("Could not find authentication button in modal")
            page.screenshot(path="auth_modal_button_not_found.png")
            return False

        try:
            auth_button.click(timeout=5000)
            print("Clicked authentication button")

            # Wait for modal to dismiss
            page.wait_for_timeout(3000)

            # Verify modal disappeared
            try:
                welcome = page.locator('text="Welcome back"')
                if not welcome.is_visible(timeout=1000):
                    print("Modal dismissed")
            except Exception:
                pass

            return True

        except Exception as e:
            print(f"Failed to click authentication button: {e}")
            page.screenshot(path="auth_modal_click_failed.png")
            return False

    def _find_account_button(self, page: Page):
        """Find account selection button with email."""
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'

        try:
            all_clickable = page.locator('[role="button"]').all()
            for elem in all_clickable:
                try:
                    if not elem.is_visible():
                        continue

                    elem_text = elem.inner_text(timeout=500).strip()
                    elem_html = elem.inner_html(timeout=500)

                    # Check if contains email
                    has_email = re.search(email_pattern, elem_text) or re.search(email_pattern, elem_html)

                    # Filter out close buttons
                    aria_label = elem.get_attribute("aria-label") or ""
                    is_remove = any(word in aria_label.lower() for word in ["remove", "close", "delete"])

                    if has_email and not is_remove:
                        bbox = elem.bounding_box()
                        if bbox and bbox['width'] > 100:
                            return elem
                except Exception:
                    continue
        except Exception:
            pass

        return None

    def _find_google_button(self, page: Page):
        """Find 'Continue with Google' button."""
        selectors = [
            'button:has-text("Continue with Google")',
            'button:text("Continue with Google")',
            '[role="button"]:has-text("Continue with Google")',
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=2000):
                    return btn
            except Exception:
                continue

        return None

    def _find_login_button(self, page: Page):
        """Find the login button in upper right."""
        selectors = [
            'button:has-text("Log in")',
            'a:has-text("Log in")',
            'header button:has-text("Log in")',
            '[role="button"]:has-text("Log in")',
        ]

        for selector in selectors:
            try:
                btn = page.locator(selector).first
                if btn.is_visible(timeout=1000):
                    return btn
            except Exception:
                continue

        return None

    def _is_chat_interface_ready(self, page: Page) -> bool:
        """Check if the chat interface is ready."""
        try:
            textarea = page.locator("#prompt-textarea")
            return textarea.is_visible(timeout=5000)
        except Exception:
            return False
