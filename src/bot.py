"""
Main orchestration module for ChatGPT automation.

This module coordinates:
- Session provider for managing authentication sessions
- Bot instances for AI evaluation
- Retry logic for obtaining citations
- Input/output operations
"""

import argparse

from playwright.sync_api import sync_playwright

from .models import SessionType, Prompt
from .session_provider import FileSessionProvider
from .bot_interface import Bot
from .chatgpt import ChatGPTBotFactory
from .io_utils import read_prompts_from_csv, ResultWriter


def create_argument_parser() -> argparse.ArgumentParser:
    """Create CLI argument parser."""
    parser = argparse.ArgumentParser(
        description="Automate ChatGPT interactions with prompts from CSV file"
    )
    parser.add_argument(
        "-i", "--input",
        default="prompts.csv",
        help="Path to input CSV file with prompts (default: prompts.csv)"
    )
    parser.add_argument(
        "-r", "--max-attempts",
        type=int,
        default=1,
        help="Maximum attempts per prompt to get citations (default: 1)"
    )
    parser.add_argument(
        "-o", "--output",
        default="chatgpt_results.json",
        help="Path to output JSON file (default: chatgpt_results.json)"
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
        result_writer: ResultWriter,
        max_attempts: int = 1,
    ) -> None:
        """
        Initialize the orchestrator.

        Args:
            session_provider: Provider for session management.
            bot_factory: Factory for creating bot instances.
            result_writer: Writer for saving results.
            max_attempts: Maximum attempts per prompt to get citations.
        """
        self._session_provider = session_provider
        self._bot_factory = bot_factory
        self._result_writer = result_writer
        self._max_attempts = max_attempts
        self._bot: Bot | None = None
        self._playwright = None

    def run(self, prompts: list[Prompt]) -> None:
        """
        Process all prompts with retry and rotation logic.

        Args:
            prompts: List of prompts to evaluate.
        """
        total = len(prompts)
        completed = 0

        print(f"Processing {total} prompts...")

        self._playwright = sync_playwright().start()
        print("Playwright initialized\n")

        try:
            for idx, prompt in enumerate(prompts, 1):
                print(f"\n{'='*60}")
                print(f"Prompt {idx}/{total} (ID: {prompt.id})")
                print(f"Text: {prompt.text}")
                print(f"{'='*60}")

                success = self._process_prompt(prompt)
                if success:
                    completed += 1

        finally:
            self._cleanup()

        print(f"\n{'='*60}")
        print(f"Completed {completed}/{total} prompts")
        print(f"Results saved to {self._result_writer._output_path}")
        print("Done!")

    def _process_prompt(self, prompt: Prompt) -> bool:
        """
        Process a single prompt with retry logic.

        Args:
            prompt: The prompt to evaluate.

        Returns:
            True if citation was found, False otherwise.
        """
        for attempt in range(1, self._max_attempts + 1):
            print(f"\n--- Attempt {attempt}/{self._max_attempts} ---")

            # Ensure bot is ready
            if not self._ensure_bot_ready():
                continue

            # For subsequent attempts, start new conversation
            if attempt > 1:
                if not self._bot.start_new_conversation():
                    print("Failed to start new conversation, will retry with fresh browser...")
                    self._reset_bot()
                    continue

            # Show session info
            session_id = self._bot.current_session_id
            print(f"[Using session: {session_id}]")

            # Evaluate prompt
            result = self._bot.evaluate(prompt.text)

            # Record evaluation with session provider
            remaining = self._session_provider.record_evaluation(session_id)
            print(f"[Session evaluations remaining: {remaining}]")

            if remaining == 0:
                print("Session exhausted, will rotate on next attempt")
                self._reset_bot()

            # Check for citations
            if result.has_citations:
                print(f"SUCCESS! Got {len(result.citations)} citations")
                self._result_writer.save_result(prompt, result, attempt)
                return True
            else:
                print(f"No citations (attempt {attempt}/{self._max_attempts})")

        # All attempts exhausted - try one more with fresh session
        print("\nAll attempts exhausted, trying fresh session...")
        self._reset_bot()

        if self._ensure_bot_ready():
            result = self._bot.evaluate(prompt.text)
            self._session_provider.record_evaluation(self._bot.current_session_id)

            if result.has_citations:
                print(f"SUCCESS with fresh session! Got {len(result.citations)} citations")
                self._result_writer.save_result(prompt, result, 1)
                return True
            else:
                print("Fresh session attempt also failed - no citations")

        # Final failure - save empty result
        print(f"All attempts failed for prompt {prompt.id}")
        self._result_writer.save_empty_result(prompt)
        return False

    def _ensure_bot_ready(self) -> bool:
        """
        Ensure bot is initialized with valid session.

        Returns:
            True if bot is ready, False otherwise.
        """
        if self._bot and self._bot.is_initialized:
            return True

        session = self._session_provider.get_session(SessionType.CHATGPT)
        if not session:
            print("No available sessions!")
            return False

        print(f"Loading session: {session.session_id}")

        self._bot = self._bot_factory.create_bot(self._playwright)
        if self._bot.initialize(session):
            print(f"Ready to use session: {session.session_id}")
            return True
        else:
            print(f"Failed to load session: {session.session_id}")
            self._session_provider.mark_invalid(session.session_id)
            self._bot = None
            return False

    def _reset_bot(self) -> None:
        """Close current bot to force session rotation."""
        if self._bot:
            print("Closing browser...")
            self._bot.close()
            self._bot = None

    def _cleanup(self) -> None:
        """Clean up all resources."""
        self._reset_bot()
        if self._playwright:
            self._playwright.stop()
            print("Playwright stopped")
            self._playwright = None


def main() -> None:
    """Main entry point."""
    args = create_argument_parser().parse_args()

    print("=== ChatGPT Automation ===")
    print(f"Input file: {args.input}")
    print(f"Output file: {args.output}")
    print(f"Sessions directory: {args.sessions_dir}")
    print(f"Max attempts per prompt: {args.max_attempts}")
    print(f"Per-session runs: {args.per_session_runs}")
    print()

    # Load prompts
    prompts = read_prompts_from_csv(args.input)
    if not prompts:
        print("No prompts found. Exiting.")
        return

    print()

    # Initialize components
    try:
        session_provider = FileSessionProvider(
            sessions_dir=args.sessions_dir,
            max_usage_per_session=args.per_session_runs,
        )
    except (FileNotFoundError, ValueError) as e:
        print(f"Error: {e}")
        print("Use scripts/create_session.py to create session files first.")
        return

    print()

    bot_factory = ChatGPTBotFactory()
    result_writer = ResultWriter(args.output)

    # Run orchestration
    orchestrator = Orchestrator(
        session_provider=session_provider,
        bot_factory=bot_factory,
        result_writer=result_writer,
        max_attempts=args.max_attempts,
    )

    orchestrator.run(prompts)


if __name__ == "__main__":
    main()
