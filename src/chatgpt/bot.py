"""ChatGPT bot implementation."""

import logging
from pathlib import Path
from typing import Optional, Any

from playwright.sync_api import Page, Browser, BrowserContext

from ..models import EvaluationResult
from .auth import ChatGPTAuthenticator
from .citation_extractor import CitationExtractor

logger = logging.getLogger(__name__)


class ChatGPTBot:
    """
    Bot implementation for ChatGPT web automation.

    Handles:
    - Browser lifecycle management
    - ChatGPT authentication (modals, login flows)
    - Prompt submission
    - Response scraping
    - Citation extraction
    """

    # Browser configuration
    LAUNCH_ARGS = [
        '--disable-blink-features=AutomationControlled',
        '--disable-dev-shm-usage',
        '--no-sandbox',
        '--disable-setuid-sandbox',
    ]
    VIEWPORT = {'width': 1280, 'height': 720}
    USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    BASE_URL = "https://chatgpt.com/"

    def __init__(self, playwright_instance: Any) -> None:
        """
        Create a ChatGPT bot.

        Args:
            playwright_instance: Active Playwright instance.
        """
        self._playwright = playwright_instance
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._is_initialized: bool = False
        self._authenticator = ChatGPTAuthenticator()
        self._citation_extractor = CitationExtractor()

    def initialize(self, storage_state: dict) -> bool:
        """
        Initialize with session and validate authentication.

        Args:
            storage_state: Playwright StorageState dict with 'cookies' and 'origins'.

        Returns:
            True if initialization successful and authenticated.
        """
        self.close()  # Clean up any existing session

        try:
            # Launch browser
            self._browser = self._playwright.chromium.launch(
                headless=False,
                args=self.LAUNCH_ARGS,
            )

            # Create context with session state
            self._context = self._browser.new_context(
                storage_state=storage_state,
                viewport=self.VIEWPORT,
                user_agent=self.USER_AGENT,
            )

            # Create page with anti-detection
            self._page = self._context.new_page()
            self._page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            # Navigate and authenticate
            self._page.goto(self.BASE_URL, timeout=60000)
            self._page.wait_for_load_state("domcontentloaded")

            if self._authenticator.authenticate_if_needed(self._page):
                self._is_initialized = True
                return True
            else:
                logger.error("Session expired or invalid")
                self.close()
                return False

        except Exception as e:
            logger.error(f"Bot initialization failed: {e}")
            self.close()
            return False

    def evaluate(self, prompt: str) -> EvaluationResult:
        """
        Submit prompt and extract response with citations.

        Args:
            prompt: The prompt text to send.

        Returns:
            EvaluationResult containing response text and citations.

        Raises:
            RuntimeError: If bot is not initialized.
        """
        if not self.is_initialized:
            raise RuntimeError("Bot not initialized. Call initialize() first.")

        try:
            # Find and fill prompt textarea
            textarea = self._page.locator("#prompt-textarea")
            textarea.fill(prompt)
            textarea.press("Enter")

            # Wait for response generation
            self._wait_for_response_complete()

            # Extract response text
            response_text = self._extract_response_text()
            if not response_text or len(response_text) < 50:
                logger.warning("Response too short or not found")

            # Extract citations
            citations = self._citation_extractor.extract(self._page)

            return EvaluationResult(
                response_text=response_text,
                citations=citations,
                success=True,
            )

        except Exception as e:
            logger.error(f"Evaluation error: {e}")
            return EvaluationResult(
                response_text="",
                citations=[],
                success=False,
                error_message=str(e),
            )

    def start_new_conversation(self) -> bool:
        """
        Navigate to fresh ChatGPT page for new conversation.

        Returns:
            True if new conversation started successfully.
        """
        if not self._page:
            return False

        try:
            self._page.goto(self.BASE_URL, timeout=60000)
            self._page.wait_for_load_state("domcontentloaded")

            if not self._authenticator.authenticate_if_needed(self._page):
                logger.warning("Authentication check completed with warnings")

            # Wait for textarea to be ready
            textarea = self._page.locator("#prompt-textarea")
            textarea.wait_for(timeout=30000)

            return True

        except Exception as e:
            logger.error(f"Failed to start new conversation: {e}")
            return False

    def close(self) -> None:
        """Close browser and clean up resources."""
        if self._page and not self._page.is_closed():
            try:
                self._page.close()
            except Exception:
                pass
        self._page = None

        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        self._browser = None
        self._context = None
        self._is_initialized = False

    @property
    def is_initialized(self) -> bool:
        """Check if the bot is initialized and ready."""
        return (
            self._is_initialized
            and self._browser is not None
            and self._page is not None
            and not self._page.is_closed()
        )

    def _wait_for_response_complete(self) -> None:
        """Wait for ChatGPT to finish generating response."""
        self._page.wait_for_timeout(2000)

        try:
            stop_button = self._page.locator('button[aria-label*="Stop"]')
            if stop_button.count() > 0:
                stop_button.wait_for(state="hidden", timeout=60000)
        except Exception:
            pass

        self._page.wait_for_timeout(2000)

    def _extract_response_text(self) -> str:
        """Extract the latest response text from the page."""
        selectors = [
            '[data-message-author-role="assistant"] .markdown',
            '[data-message-author-role="assistant"]',
            'article[data-testid*="conversation-turn"] .markdown',
            'article[data-testid*="conversation-turn"]',
            '.markdown',
            '[class*="agent-turn"]',
            'div[class*="markdown"]',
        ]

        for selector in selectors:
            try:
                messages = self._page.locator(selector).all()
                if messages:
                    response_text = messages[-1].inner_text()
                    if response_text and len(response_text) > 50:
                        return response_text
            except Exception:
                continue

        # Fallback: parse page text
        try:
            self._page.locator("body").inner_text()
            return "No response found"
        except Exception:
            return "No response found"


class ChatGPTBotFactory:
    """Factory for creating ChatGPTBot instances."""

    def create_bot(self, playwright_instance: Any) -> ChatGPTBot:
        """
        Create a new ChatGPT bot instance.

        Args:
            playwright_instance: Active Playwright instance.

        Returns:
            A new ChatGPTBot instance (not yet initialized).
        """
        return ChatGPTBot(playwright_instance)
