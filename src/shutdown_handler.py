"""Graceful shutdown handling for long-running processes."""

import signal
import logging
from threading import Event
from types import FrameType
from typing import Optional

logger = logging.getLogger(__name__)


class ShutdownHandler:
    """
    Manages graceful shutdown for long-running processes.

    Handles SIGINT (Ctrl+C) and SIGTERM signals, setting an event
    that can be checked by the main loop to terminate gracefully.
    """

    def __init__(self) -> None:
        """Initialize shutdown handler with threading event."""
        self._shutdown_event = Event()
        self._original_sigint_handler = None
        self._original_sigterm_handler = None

    def install_signal_handlers(self) -> None:
        """Install signal handlers for SIGINT and SIGTERM."""
        self._original_sigint_handler = signal.signal(
            signal.SIGINT,
            self._handle_signal
        )
        self._original_sigterm_handler = signal.signal(
            signal.SIGTERM,
            self._handle_signal
        )
        logger.debug("Installed shutdown signal handlers")

    def _handle_signal(self, signum: int, frame: Optional[FrameType]) -> None:
        """Handle shutdown signals by setting the shutdown event."""
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        logger.info(f"Received {signal_name}, initiating graceful shutdown...")
        self._shutdown_event.set()

    def request_shutdown(self) -> None:
        """Programmatically request shutdown (for tests, health checks)."""
        logger.info("Shutdown requested programmatically")
        self._shutdown_event.set()

    @property
    def should_shutdown(self) -> bool:
        """Check if shutdown has been requested."""
        return self._shutdown_event.is_set()

    @property
    def shutdown_event(self) -> Event:
        """Get the underlying threading.Event for interruptible waits."""
        return self._shutdown_event

    def restore_signal_handlers(self) -> None:
        """Restore original signal handlers (cleanup)."""
        if self._original_sigint_handler:
            signal.signal(signal.SIGINT, self._original_sigint_handler)
        if self._original_sigterm_handler:
            signal.signal(signal.SIGTERM, self._original_sigterm_handler)
        logger.debug("Restored original signal handlers")
