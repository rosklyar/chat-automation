"""Tests for polling backoff behavior."""

import pytest

from src.models import PollingState, PollingConfig
from src.bot import PollingBackoff


class TestPollingConfig:
    """Tests for PollingConfig dataclass."""

    def test_default_values(self):
        """Test PollingConfig has sensible defaults."""
        config = PollingConfig()
        assert config.base_interval == 5.0
        assert config.max_interval == 300.0
        assert config.backoff_multiplier == 2.0
        assert config.api_error_interval == 300.0
        assert config.browser_close_threshold == 60.0

    def test_custom_values(self):
        """Test PollingConfig accepts custom values."""
        config = PollingConfig(
            base_interval=10.0,
            max_interval=600.0,
            backoff_multiplier=3.0,
            api_error_interval=120.0,
            browser_close_threshold=30.0,
        )
        assert config.base_interval == 10.0
        assert config.max_interval == 600.0
        assert config.backoff_multiplier == 3.0
        assert config.api_error_interval == 120.0
        assert config.browser_close_threshold == 30.0


class TestPollingBackoff:
    """Tests for PollingBackoff class."""

    def test_initial_state(self):
        """Test backoff starts in ACTIVE state with base interval."""
        config = PollingConfig(base_interval=5.0)
        backoff = PollingBackoff(config)

        assert backoff.state == PollingState.ACTIVE
        assert backoff.current_interval == 5.0
        assert not backoff.should_close_browser

    def test_on_prompt_received_resets_to_base(self):
        """Test on_prompt_received resets interval to base."""
        config = PollingConfig(base_interval=5.0)
        backoff = PollingBackoff(config)

        # Simulate some backoff
        backoff.on_no_prompts()
        backoff.on_no_prompts()
        assert backoff.current_interval > 5.0

        # Receive a prompt
        backoff.on_prompt_received()

        assert backoff.state == PollingState.ACTIVE
        assert backoff.current_interval == 5.0

    def test_on_prompt_received_resets_from_disconnected(self):
        """Test on_prompt_received resets from DISCONNECTED state."""
        config = PollingConfig(base_interval=5.0)
        backoff = PollingBackoff(config)

        # Simulate API error
        backoff.on_api_error()
        assert backoff.state == PollingState.DISCONNECTED

        # Receive a prompt
        backoff.on_prompt_received()

        assert backoff.state == PollingState.ACTIVE
        assert backoff.current_interval == 5.0

    def test_on_no_prompts_exponential_growth(self):
        """Test on_no_prompts grows interval exponentially."""
        config = PollingConfig(
            base_interval=5.0,
            backoff_multiplier=2.0,
            max_interval=300.0,
        )
        backoff = PollingBackoff(config)

        # First call returns current interval (5) and doubles for next
        interval1 = backoff.on_no_prompts()
        assert interval1 == 5.0
        assert backoff.current_interval == 10.0

        # Second call returns 10 and doubles to 20
        interval2 = backoff.on_no_prompts()
        assert interval2 == 10.0
        assert backoff.current_interval == 20.0

        # Third call returns 20 and doubles to 40
        interval3 = backoff.on_no_prompts()
        assert interval3 == 20.0
        assert backoff.current_interval == 40.0

    def test_on_no_prompts_sets_idle_state(self):
        """Test on_no_prompts sets state to IDLE_NO_PROMPTS."""
        config = PollingConfig()
        backoff = PollingBackoff(config)

        backoff.on_no_prompts()

        assert backoff.state == PollingState.IDLE_NO_PROMPTS

    def test_on_no_prompts_caps_at_max(self):
        """Test on_no_prompts caps interval at max_interval."""
        config = PollingConfig(
            base_interval=100.0,
            backoff_multiplier=2.0,
            max_interval=300.0,
        )
        backoff = PollingBackoff(config)

        # First: 100 -> 200
        backoff.on_no_prompts()
        assert backoff.current_interval == 200.0

        # Second: 200 -> 300 (capped)
        backoff.on_no_prompts()
        assert backoff.current_interval == 300.0

        # Third: still 300 (capped)
        backoff.on_no_prompts()
        assert backoff.current_interval == 300.0

    def test_on_api_error_returns_fixed_interval(self):
        """Test on_api_error returns fixed api_error_interval."""
        config = PollingConfig(
            base_interval=5.0,
            api_error_interval=300.0,
        )
        backoff = PollingBackoff(config)

        interval = backoff.on_api_error()

        assert interval == 300.0
        assert backoff.state == PollingState.DISCONNECTED

    def test_on_api_error_resets_backoff(self):
        """Test on_api_error resets the backoff to base interval."""
        config = PollingConfig(base_interval=5.0)
        backoff = PollingBackoff(config)

        # Grow backoff
        backoff.on_no_prompts()
        backoff.on_no_prompts()
        assert backoff.current_interval > 5.0

        # API error resets to base
        backoff.on_api_error()

        assert backoff.current_interval == 5.0

    def test_should_close_browser_below_threshold(self):
        """Test should_close_browser is False when below threshold."""
        config = PollingConfig(
            base_interval=5.0,
            browser_close_threshold=60.0,
        )
        backoff = PollingBackoff(config)

        # At 5s, should not close
        assert not backoff.should_close_browser

        # At 10s, should not close
        backoff.on_no_prompts()
        assert not backoff.should_close_browser

        # At 20s, should not close
        backoff.on_no_prompts()
        assert not backoff.should_close_browser

        # At 40s, should not close
        backoff.on_no_prompts()
        assert not backoff.should_close_browser

    def test_should_close_browser_above_threshold(self):
        """Test should_close_browser is True when last wait interval exceeds threshold."""
        config = PollingConfig(
            base_interval=5.0,
            backoff_multiplier=2.0,
            browser_close_threshold=60.0,
        )
        backoff = PollingBackoff(config)

        # Progress through: 5 -> 10 -> 20 -> 40 -> 80
        backoff.on_no_prompts()  # returns 5, next is 10
        backoff.on_no_prompts()  # returns 10, next is 20
        backoff.on_no_prompts()  # returns 20, next is 40
        backoff.on_no_prompts()  # returns 40, next is 80
        interval = backoff.on_no_prompts()  # returns 80, next is 160

        assert interval == 80.0
        assert backoff.should_close_browser

    def test_backoff_progression_matches_documentation(self):
        """Test backoff progression matches documented behavior.

        With defaults (base=5s, multiplier=2.0, max=300s, threshold=60s):
        Poll 1: 5s (browser open)
        Poll 2: 10s (browser open)
        Poll 3: 20s (browser open)
        Poll 4: 40s (browser open)
        Poll 5: 80s (browser closes)
        Poll 6: 160s (browser closed)
        Poll 7+: 300s (capped)
        """
        config = PollingConfig()  # Use defaults
        backoff = PollingBackoff(config)

        # Poll 1: 5s, browser open
        interval = backoff.on_no_prompts()
        assert interval == 5.0
        assert not backoff.should_close_browser

        # Poll 2: 10s, browser open
        interval = backoff.on_no_prompts()
        assert interval == 10.0
        assert not backoff.should_close_browser

        # Poll 3: 20s, browser open
        interval = backoff.on_no_prompts()
        assert interval == 20.0
        assert not backoff.should_close_browser

        # Poll 4: 40s, browser open
        interval = backoff.on_no_prompts()
        assert interval == 40.0
        assert not backoff.should_close_browser

        # Poll 5: 80s, browser closes (80 > 60)
        interval = backoff.on_no_prompts()
        assert interval == 80.0
        assert backoff.should_close_browser

        # Poll 6: 160s
        interval = backoff.on_no_prompts()
        assert interval == 160.0

        # Poll 7: 300s (capped at max)
        interval = backoff.on_no_prompts()
        assert interval == 300.0

        # Poll 8: still 300s
        interval = backoff.on_no_prompts()
        assert interval == 300.0

    def test_custom_multiplier(self):
        """Test backoff with custom multiplier."""
        config = PollingConfig(
            base_interval=10.0,
            backoff_multiplier=3.0,
            max_interval=1000.0,
        )
        backoff = PollingBackoff(config)

        # 10 -> 30 -> 90 -> 270 -> 810
        interval1 = backoff.on_no_prompts()
        assert interval1 == 10.0

        interval2 = backoff.on_no_prompts()
        assert interval2 == 30.0

        interval3 = backoff.on_no_prompts()
        assert interval3 == 90.0

        interval4 = backoff.on_no_prompts()
        assert interval4 == 270.0

        interval5 = backoff.on_no_prompts()
        assert interval5 == 810.0
