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

from .models import Prompt, EvaluationResult
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
        "--poll-retry-seconds",
        type=float,
        default=5.0,
        help="Seconds to wait when no prompts available (default: 5.0)"
    )
    parser.add_argument(
        "--idle-timeout-minutes",
        type=float,
        default=None,
        help="Close browser after N minutes of inactivity (default: never)"
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
    return parser


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
        poll_retry_seconds: float = 5.0,
        idle_timeout_minutes: Optional[float] = None,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            session_provider: Provider for session management.
            bot_factory: Factory for creating bot instances.
            prompt_provider: Provider for sourcing prompts.
            result_persister: Persister for storing results.
            max_attempts: Maximum attempts per prompt to get citations.
            poll_retry_seconds: Seconds to wait when poll() returns None.
            idle_timeout_minutes: Close browser after N minutes idle (None = never).
        """
        self._session_provider = session_provider
        self._bot_factory = bot_factory
        self._prompt_provider = prompt_provider
        self._result_persister = result_persister
        self._max_attempts = max_attempts
        self._poll_retry_seconds = poll_retry_seconds
        self._idle_timeout_seconds = (
            idle_timeout_minutes * 60 if idle_timeout_minutes else None
        )
        self._bot: Bot | None = None
        self._playwright = None
        self._shutdown_handler = ShutdownHandler()
        self._last_prompt_time: Optional[float] = None

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
                    # Poll for next prompt
                    prompt = self._prompt_provider.poll()

                    if prompt is None:
                        # No prompt available - wait and retry
                        logger.debug(
                            f"No prompts available, waiting {self._poll_retry_seconds}s..."
                        )

                        # Check for idle timeout
                        self._check_idle_timeout()

                        # Interruptible wait using shutdown event
                        self._shutdown_handler.shutdown_event.wait(
                            timeout=self._poll_retry_seconds
                        )
                        continue

                    # Process the prompt
                    processed += 1
                    self._last_prompt_time = time.time()
                    logger.info(
                        f"\nPrompt {processed} (ID: {prompt.id}): {prompt.text[:100]}..."
                    )

                    success = self._process_prompt(prompt)
                    if success:
                        completed += 1

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

        Args:
            prompt: The prompt to evaluate.

        Returns:
            True if citation was found, False otherwise.
        """
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

            # Record evaluation - CHECK FOR EAGER ROTATION
            recorded = self._session_provider.record_evaluation()
            if recorded.rotated:
                logger.info("Session exhausted, resetting browser")
                self._reset_bot()

            # Check for citations
            if result.has_citations:
                logger.info(f"✓ Got {len(result.citations)} citations")
                self._result_persister.save(prompt, result, attempt)
                return True

        # All attempts exhausted - try ONCE with fresh session (manual fallback)
        logger.info("Switching to fresh session for final retry")
        self._session_provider.force_rotate()
        self._reset_bot()

        if self._ensure_bot_ready():
            # Start fresh conversation for final attempt
            if not self._bot.start_new_conversation():
                logger.warning("Failed to start new conversation for final retry")
            else:
                result = self._bot.evaluate(prompt.text)
                recorded = self._session_provider.record_evaluation()
                if recorded.rotated:
                    self._reset_bot()

                if result.has_citations:
                    logger.info(f"✓ Got citations with fresh session")
                    self._result_persister.save(prompt, result, 1)
                    return True

        # Final failure - save empty result
        logger.error(f"✗ Failed to get citations for prompt {prompt.id}")
        empty_result = EvaluationResult(
            response_text="",
            citations=[],
            success=False,
            error_message=f"No citations found after {self._max_attempts} attempts"
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

    def _check_idle_timeout(self) -> None:
        """Close browser if idle timeout exceeded."""
        if self._idle_timeout_seconds is None:
            return

        if self._last_prompt_time is None:
            return

        idle_duration = time.time() - self._last_prompt_time

        if idle_duration > self._idle_timeout_seconds:
            logger.info(
                f"Idle timeout ({self._idle_timeout_seconds/60:.1f} min) exceeded, "
                f"closing browser to save resources"
            )
            self._reset_bot()
            self._last_prompt_time = None  # Reset timer

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
            submit_retry_attempts=args.submit_retry_attempts,
            timeout_seconds=args.submit_timeout
        )
    except (ValueError, PersistenceError) as e:
        logger.error(f"Error initializing result persister: {e}")
        return
    except Exception as e:
        logger.error(f"Unexpected error initializing result persister: {e}")
        return

    # Run orchestration
    orchestrator = Orchestrator(
        session_provider=session_provider,
        bot_factory=bot_factory,
        prompt_provider=prompt_provider,
        result_persister=result_persister,
        max_attempts=args.max_attempts,
        poll_retry_seconds=args.poll_retry_seconds,
        idle_timeout_minutes=args.idle_timeout_minutes,
    )

    orchestrator.run()


if __name__ == "__main__":
    main()
