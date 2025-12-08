"""Bot protocol definitions for AI assistant automation."""

from typing import Protocol, runtime_checkable, Any

from .models import EvaluationResult


@runtime_checkable
class Bot(Protocol):
    """
    Protocol for AI assistant bots that can evaluate prompts.

    A Bot encapsulates all interaction with a specific AI assistant,
    including:
    - Browser/page management
    - Authentication
    - Prompt submission
    - Response and citation extraction

    Implementations should be stateful, maintaining an active browser
    session for multiple evaluations.
    """

    def initialize(self, storage_state: dict) -> bool:
        """
        Initialize the bot with a session.

        Launches browser, loads session state, and validates authentication.

        Args:
            storage_state: Playwright StorageState dict with 'cookies' and 'origins'.

        Returns:
            True if initialization successful and authenticated.
        """
        ...

    def evaluate(self, prompt: str) -> EvaluationResult:
        """
        Evaluate a prompt and return the result with citations.

        Args:
            prompt: The prompt text to send to the AI assistant.

        Returns:
            EvaluationResult containing response text and citations.

        Raises:
            RuntimeError: If bot is not initialized.
        """
        ...

    def start_new_conversation(self) -> bool:
        """
        Start a fresh conversation, clearing previous context.

        Returns:
            True if new conversation started successfully.
        """
        ...

    def close(self) -> None:
        """
        Close the bot, releasing browser resources.

        Safe to call multiple times.
        """
        ...

    @property
    def is_initialized(self) -> bool:
        """Check if the bot is initialized and ready for evaluation."""
        ...


@runtime_checkable
class BotFactory(Protocol):
    """Factory for creating Bot instances."""

    def create_bot(self, playwright_instance: Any) -> Bot:
        """
        Create a new bot instance.

        Args:
            playwright_instance: Active Playwright instance to use.

        Returns:
            A new Bot instance (not yet initialized).
        """
        ...
