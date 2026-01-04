"""
Main orchestration module for ChatGPT automation.

This module coordinates:
- Session provider for managing authentication sessions
- Bot instances for AI evaluation
- Retry logic for obtaining citations
- Input/output operations
"""

import argparse
import logging
import time
from pathlib import Path
from typing import Optional

from playwright.sync_api import sync_playwright

from .models import Prompt, EvaluationResult, PollingState, PollingConfig
from .session_provider import FileSessionProvider
from .bot_interface import Bot
from .chatgpt import ChatGPTBotFactory
from .prompt_provider import (
    PromptProvider,
    HttpApiPromptProvider,
    ApiProviderError
)
from .result_persister import (
    ResultPersister,
    HttpApiResultPersister,
    PersistenceError
)
from .logging_config import setup_logging
from .shutdown_handler import ShutdownHandler

logger = logging.getLogger(__name__)


def _has_valid_response(result: EvaluationResult) -> bool:
    """Check if result contains a valid, submittable response."""
    return result.success and bool(result.response_text.strip())


def _is_better_result(
    new_result: EvaluationResult,
    current_best: Optional[EvaluationResult]
) -> bool:
    """
    Determine if new_result should replace current_best.

    Priority: has_citations > has_valid_response > nothing
    """
    if current_best is None:
        return True

    if new_result.has_citations and not current_best.has_citations:
        return True

    if _has_valid_response(new_result) and not _has_valid_response(current_best):
        return True

    return False


def create_argument_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Automate ChatGPT interactions with continuous prompt polling"
    )

    # Prompt source (HTTP API only)
    parser.add_argument(
        "--api-url",
        required=True,
        help="Base URL for HTTP API prompt source (e.g., http://localhost:8000)"
    )

    # API-specific options
    parser.add_argument(
        "--assistant-name",
        default="ChatGPT",
        help="Assistant name for API requests (default: ChatGPT)"
    )
    parser.add_argument(
        "--plan-name",
        default="Plus",
        help="Plan name for API requests (default: Plus)"
    )
    parser.add_argument(
        "--api-timeout",
        type=float,
        default=30.0,
        help="API request timeout in seconds (default: 30.0)"
    )
    parser.add_argument(
        "--poll-base-interval",
        type=float,
        default=5.0,
        help="Base polling interval in seconds (default: 5.0)"
    )
    parser.add_argument(
        "--poll-max-interval",
        type=float,
        default=300.0,
        help="Maximum polling interval in seconds (default: 300 = 5 min)"
    )
    parser.add_argument(
        "--poll-backoff-multiplier",
        type=float,
        default=2.0,
        help="Backoff multiplier for exponential growth (default: 2.0)"
    )
    parser.add_argument(
        "--api-error-retry-interval",
        type=float,
        default=300.0,
        help="Fixed retry interval when API is unreachable (default: 300 = 5 min)"
    )
    parser.add_argument(
        "--browser-close-threshold",
        type=float,
        default=60.0,
        help="Close browser when wait exceeds this many seconds (default: 60)"
    )
    parser.add_argument(
        "-r", "--max-attempts",
        type=int,
        default=1,
        help="Maximum attempts per prompt to get citations (default: 1)"
    )

    # Result output (HTTP API only)
    parser.add_argument(
        "--results-api-url",
        required=True,
        help="Base URL for HTTP API result submission (e.g., http://localhost:8000)"
    )

    # HTTP API result persister options
    parser.add_argument(
        "--submit-retry-attempts",
        type=int,
        default=3,
        help="Max retry attempts for submitting results to API (default: 3)"
    )
    parser.add_argument(
        "--submit-timeout",
        type=float,
        default=30.0,
        help="API request timeout in seconds for result submission (default: 30.0)"
    )
    parser.add_argument(
        "--sessions-dir",
        required=True,
        help="Directory containing session files (use scripts/create_session.py to create)"
    )
    parser.add_argument(
        "--per-session-runs",
        type=int,
        default=10,
        help="Evaluations per session before rotation (default: 10)"
    )
    parser.add_argument(
        "--log-level",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        default="INFO",
        help="Set logging level (default: INFO)"
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        help="Optional log file path for persistent logging"
    )
    parser.add_argument(
        "--bot-secret",
        required=True,
        help="Secret token for X-Bot-Secret header authentication"
    )
    return parser


class PollingBackoff:
    """Manages exponential backoff for polling with browser lifecycle awareness."""

    def __init__(self, config: PollingConfig) -> None:
        self._config = config
        self._current_interval = config.base_interval
        self._last_wait_interval = config.base_interval
        self._state = PollingState.ACTIVE

    @property
    def state(self) -> PollingState:
        """Current polling state."""
        return self._state

    @property
    def current_interval(self) -> float:
        """Current wait interval in seconds."""
        return self._current_interval

    @property
    def should_close_browser(self) -> bool:
        """True if last returned wait interval exceeds browser close threshold."""
        return self._last_wait_interval > self._config.browser_close_threshold

    def on_prompt_received(self) -> None:
        """Reset backoff when prompt is successfully received."""
        self._current_interval = self._config.base_interval
        self._last_wait_interval = self._config.base_interval
        self._state = PollingState.ACTIVE

    def on_no_prompts(self) -> float:
        """Called when API returns no prompts. Returns wait interval."""
        self._state = PollingState.IDLE_NO_PROMPTS
        interval = self._current_interval
        self._last_wait_interval = interval
        # Grow for next time, but cap at max
        self._current_interval = min(
            self._current_interval * self._config.backoff_multiplier,
            self._config.max_interval
        )
        return interval

    def on_api_error(self) -> float:
        """Called when API is unreachable. Returns fixed 5-min interval."""
        self._state = PollingState.DISCONNECTED
        self._current_interval = self._config.base_interval  # Reset backoff
        return self._config.api_error_interval


class Orchestrator:
    """
    Coordinates prompt evaluation with session management and retry logic.

    Responsibilities:
    - Initialize and manage bot lifecycle
    - Handle session rotation based on usage
    - Implement retry-until-citations logic
    - Save results after successful evaluations
    """

    def __init__(
        self,
        session_provider: FileSessionProvider,
        bot_factory: ChatGPTBotFactory,
        prompt_provider: PromptProvider,
        result_persister: ResultPersister,
        max_attempts: int = 1,
        polling_config: Optional[PollingConfig] = None,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            session_provider: Provider for session management.
            bot_factory: Factory for creating bot instances.
            prompt_provider: Provider for sourcing prompts.
            result_persister: Persister for storing results.
            max_attempts: Maximum attempts per prompt to get citations.
            polling_config: Configuration for polling backoff behavior.
        """
        self._session_provider = session_provider
        self._bot_factory = bot_factory
        self._prompt_provider = prompt_provider
        self._result_persister = result_persister
        self._max_attempts = max_attempts
        self._backoff = PollingBackoff(polling_config or PollingConfig())
        self._bot: Bot | None = None
        self._playwright = None
        self._shutdown_handler = ShutdownHandler()

    def run(self) -> None:
        """Process prompts continuously with retry and rotation logic."""
        processed = 0
        completed = 0

        logger.info("Starting continuous prompt processing (Ctrl+C to stop)")

        # Install signal handlers
        self._shutdown_handler.install_signal_handlers()

        self._playwright = sync_playwright().start()

        try:
            with self._prompt_provider:
                while not self._shutdown_handler.should_shutdown:
                    # Poll for next prompt with error handling
                    try:
                        prompt = self._prompt_provider.poll()
                    except ApiProviderError as e:
                        # API unreachable - go to disconnected state
                        logger.warning(f"API unreachable: {e}")
                        wait_interval = self._backoff.on_api_error()
                        self._enter_idle_mode(wait_interval)
                        continue

                    if prompt is None:
                        # No prompts available - exponential backoff
                        wait_interval = self._backoff.on_no_prompts()
                        logger.debug(
                            f"No prompts available, waiting {wait_interval:.1f}s..."
                        )

                        if self._backoff.should_close_browser:
                            self._enter_idle_mode(wait_interval)
                        else:
                            self._shutdown_handler.shutdown_event.wait(
                                timeout=wait_interval
                            )
                        continue

                    # Prompt received - reset backoff
                    self._backoff.on_prompt_received()
                    processed += 1
                    logger.info(
                        f"\nPrompt {processed} (ID: {prompt.id}): {prompt.text[:100]}..."
                    )

                    try:
                        success = self._process_prompt(prompt)
                        if success:
                            completed += 1
                    except PersistenceError as e:
                        # Submission failed - go to idle mode
                        logger.warning(f"Submission failed: {e}")
                        wait_interval = self._backoff.on_api_error()
                        self._enter_idle_mode(wait_interval)
                        continue

        finally:
            self._shutdown_handler.restore_signal_handlers()
            self._cleanup()

        logger.info(
            f"\nShutdown complete. Processed {completed}/{processed} prompts - "
            f"Results saved to {self._result_persister.output_location}"
        )

    def _process_prompt(self, prompt: Prompt) -> bool:
        """
        Process a single prompt with retry logic.

        Tries up to max_attempts times to get a response with citations.
        Tracks the best result seen (preferring citations over no citations).
        Submits the best available result at the end.

        Args:
            prompt: The prompt to evaluate.

        Returns:
            True if a valid response was obtained, False if complete failure.
        """
        best_result: Optional[EvaluationResult] = None
        best_attempt: int = 0

        # Main retry loop - try to get citations
        for attempt in range(1, self._max_attempts + 1):
            # Ensure bot is ready
            if not self._ensure_bot_ready():
                continue

            # Start fresh conversation for EVERY evaluation attempt
            if not self._bot.start_new_conversation():
                logger.warning("Failed to start new conversation, retrying with fresh browser")
                self._reset_bot()
                continue

            # Evaluate prompt
            result = self._bot.evaluate(prompt.text)

            # Track best result seen so far
            if _is_better_result(result, best_result):
                best_result = result
                best_attempt = attempt

            # Record evaluation - CHECK FOR EAGER ROTATION
            recorded = self._session_provider.record_evaluation()
            if recorded.rotated:
                logger.info("Session exhausted, resetting browser")
                self._reset_bot()

            # If we got citations, we're done - submit immediately
            if result.has_citations:
                logger.info(f"✓ Got {len(result.citations)} citations on attempt {attempt}")
                self._result_persister.save(prompt, result, attempt)
                return True

        # All attempts exhausted without citations - try ONCE with fresh session
        logger.info("Switching to fresh session for final retry")
        self._session_provider.force_rotate()
        self._reset_bot()

        if self._ensure_bot_ready():
            # Start fresh conversation for final attempt
            if not self._bot.start_new_conversation():
                logger.warning("Failed to start new conversation for final retry")
            else:
                result = self._bot.evaluate(prompt.text)

                # Track if this is better
                if _is_better_result(result, best_result):
                    best_result = result
                    best_attempt = self._max_attempts + 1  # Fresh session attempt

                recorded = self._session_provider.record_evaluation()
                if recorded.rotated:
                    self._reset_bot()

                if result.has_citations:
                    logger.info("✓ Got citations with fresh session")
                    self._result_persister.save(prompt, result, 1)
                    return True

        # No citations found - check if we have ANY valid response
        if best_result is not None and _has_valid_response(best_result):
            # Submit the best response we have (without citations)
            logger.info(
                f"No citations found, but submitting valid response from attempt {best_attempt}"
            )
            self._result_persister.save(prompt, best_result, best_attempt)
            return True

        # Complete failure - no valid response obtained
        logger.error(f"✗ Failed to get any valid response for prompt {prompt.id}")
        empty_result = EvaluationResult(
            response_text="",
            citations=[],
            success=False,
            error_message=f"No valid response after {self._max_attempts} attempts"
        )
        self._result_persister.save(prompt, empty_result, run_number=0)
        return False

    def _ensure_bot_ready(self) -> bool:
        """
        Ensure bot is initialized with valid session.

        Returns:
            True if bot is ready, False otherwise.
        """
        if self._bot and self._bot.is_initialized:
            return True

        storage_state = self._session_provider.get_session()
        if not storage_state:
            logger.error("No available sessions")
            return False

        self._bot = self._bot_factory.create_bot(self._playwright)
        if self._bot.initialize(storage_state):
            return True
        else:
            logger.error(f"Failed to load session: {self._session_provider.current_session_name}")
            self._session_provider.force_rotate()
            self._bot = None
            return False

    def _reset_bot(self) -> None:
        """Close current bot to force session rotation."""
        if self._bot:
            self._bot.close()
            self._bot = None

    def _enter_idle_mode(self, wait_interval: float) -> None:
        """Close browser and wait for specified interval."""
        if self._bot:
            logger.info(
                f"Entering idle mode (state: {self._backoff.state.name}), "
                f"closing browser, waiting {wait_interval / 60:.1f} min..."
            )
            self._reset_bot()

        self._shutdown_handler.shutdown_event.wait(timeout=wait_interval)

    def _cleanup(self) -> None:
        """Clean up all resources."""
        self._reset_bot()
        if self._playwright:
            self._playwright.stop()
            self._playwright = None


def main() -> None:
    """Main entry point."""
    args = create_argument_parser().parse_args()

    # Setup logging first
    setup_logging(level=args.log_level, log_file=args.log_file)

    # Create HTTP API prompt provider
    prompt_provider: PromptProvider
    try:
        prompt_provider = HttpApiPromptProvider(
            api_base_url=args.api_url,
            assistant_name=args.assistant_name,
            plan_name=args.plan_name,
            bot_secret=args.bot_secret,
            timeout_seconds=args.api_timeout
        )
    except (ValueError, ApiProviderError) as e:
        logger.error(f"Error initializing prompt provider: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error loading prompts: {e}")
        return

    # Initialize components
    try:
        session_provider = FileSessionProvider(
            sessions_dir=args.sessions_dir,
            max_usage_per_session=args.per_session_runs,
        )
    except (FileNotFoundError, ValueError) as e:
        logger.error(f"{e}")
        logger.error("Use scripts/create_session.py to create session files first")
        return

    bot_factory = ChatGPTBotFactory()

    # Create HTTP API result persister
    result_persister: ResultPersister
    try:
        result_persister = HttpApiResultPersister(
            api_base_url=args.results_api_url,
            bot_secret=args.bot_secret,
            submit_retry_attempts=args.submit_retry_attempts,
            timeout_seconds=args.submit_timeout
        )
    except (ValueError, PersistenceError) as e:
        logger.error(f"Error initializing result persister: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error initializing result persister: {e}")
        return

    # Create polling configuration
    polling_config = PollingConfig(
        base_interval=args.poll_base_interval,
        max_interval=args.poll_max_interval,
        backoff_multiplier=args.poll_backoff_multiplier,
        api_error_interval=args.api_error_retry_interval,
        browser_close_threshold=args.browser_close_threshold,
    )

    # Run orchestration
    orchestrator = Orchestrator(
        session_provider=session_provider,
        bot_factory=bot_factory,
        prompt_provider=prompt_provider,
        result_persister=result_persister,
        max_attempts=args.max_attempts,
        polling_config=polling_config,
    )

    orchestrator.run()


if __name__ == "__main__":
    main()
