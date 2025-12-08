"""Tests for graceful shutdown handling."""

import signal
import time
from threading import Thread

import pytest

from src.shutdown_handler import ShutdownHandler


class TestShutdownHandler:
    """Tests for ShutdownHandler."""

    def test_initial_state(self):
        """Test handler starts without shutdown requested."""
        handler = ShutdownHandler()
        assert not handler.should_shutdown

    def test_programmatic_shutdown(self):
        """Test requesting shutdown programmatically."""
        handler = ShutdownHandler()
        handler.request_shutdown()
        assert handler.should_shutdown

    def test_shutdown_event_property(self):
        """Test shutdown_event property provides Event object."""
        handler = ShutdownHandler()

        # Event should timeout when not set
        signaled = handler.shutdown_event.wait(timeout=0.1)
        assert not signaled

        # Request shutdown
        handler.request_shutdown()

        # Event should be set immediately
        signaled = handler.shutdown_event.wait(timeout=0.1)
        assert signaled

    def test_signal_handlers_installed(self):
        """Test that signal handlers are installed."""
        handler = ShutdownHandler()

        original_sigint = signal.getsignal(signal.SIGINT)

        handler.install_signal_handlers()

        # Handler should be changed
        new_sigint = signal.getsignal(signal.SIGINT)
        assert new_sigint != original_sigint

        # Cleanup
        handler.restore_signal_handlers()

        # Handler should be restored
        restored_sigint = signal.getsignal(signal.SIGINT)
        assert restored_sigint == original_sigint

    def test_interruptible_wait(self):
        """Test that shutdown can interrupt waiting."""
        handler = ShutdownHandler()
        handler.install_signal_handlers()

        try:
            # Start a thread that will wait
            wait_completed = []

            def waiter():
                # Wait up to 10 seconds (should be interrupted)
                start = time.time()
                handler.shutdown_event.wait(timeout=10.0)
                duration = time.time() - start
                wait_completed.append(duration)

            thread = Thread(target=waiter)
            thread.start()

            # Give thread time to start waiting
            time.sleep(0.1)

            # Request shutdown
            handler.request_shutdown()

            # Wait for thread
            thread.join(timeout=1.0)

            # Wait should have been interrupted quickly (< 1 second, not 10)
            assert len(wait_completed) == 1
            assert wait_completed[0] < 1.0

        finally:
            handler.restore_signal_handlers()
