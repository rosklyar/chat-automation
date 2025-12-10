"""Tests for HTTP API prompt provider."""

import json
import pytest
import responses
from requests.exceptions import Timeout, ConnectionError

from src.models import Prompt
from src.prompt_provider import HttpApiPromptProvider, ApiProviderError


class TestHttpApiPromptProvider:
    """Tests for HttpApiPromptProvider implementation."""

    @pytest.fixture
    def base_url(self) -> str:
        """Base URL for mock API."""
        return "https://api.example.com"

    @pytest.fixture
    def poll_url(self, base_url: str) -> str:
        """Poll endpoint URL."""
        return f"{base_url}/evaluations/api/v1/poll"

    def test_initialization_success(self, base_url: str):
        """Test successful initialization with valid parameters."""
        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )
        assert not provider.is_exhausted
        assert provider._poll_endpoint == f"{base_url}/evaluations/api/v1/poll"

    def test_initialization_removes_trailing_slash(self):
        """Test that trailing slash is removed from base URL."""
        provider = HttpApiPromptProvider(
            api_base_url="https://api.example.com/",
            assistant_name="ChatGPT",
            plan_name="Plus"
        )
        assert provider._poll_endpoint == "https://api.example.com/evaluations/api/v1/poll"

    def test_initialization_with_empty_url(self):
        """Test initialization fails with empty URL."""
        with pytest.raises(ValueError, match="cannot be empty"):
            HttpApiPromptProvider(
                api_base_url="",
                assistant_name="ChatGPT",
                plan_name="Plus"
            )

    def test_initialization_with_missing_credentials(self, base_url: str):
        """Test initialization fails without assistant/plan names."""
        with pytest.raises(ValueError, match="required"):
            HttpApiPromptProvider(
                api_base_url=base_url,
                assistant_name="",
                plan_name="Plus"
            )

    @responses.activate
    def test_poll_returns_prompt(self, base_url: str, poll_url: str):
        """Test successful poll returns prompt with metadata."""
        responses.post(
            poll_url,
            json={
                "evaluation_id": 123,
                "prompt_id": 456,
                "prompt_text": "What is Python?",
                "topic_id": 1,
                "claimed_at": "2025-12-09T10:30:00Z"
            },
            status=200
        )

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )

        prompt = provider.poll()
        assert prompt is not None
        assert prompt.id == "456"
        assert prompt.text == "What is Python?"
        assert prompt.evaluation_id == 123
        assert prompt.topic_id == 1
        assert prompt.claimed_at == "2025-12-09T10:30:00Z"

    @responses.activate
    def test_poll_returns_none_when_empty(self, base_url: str, poll_url: str):
        """Test poll returns None when API has no prompts."""
        responses.post(
            poll_url,
            json={
                "evaluation_id": None,
                "prompt_id": None,
                "prompt_text": None,
                "topic_id": None,
                "claimed_at": None
            },
            status=200
        )

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )

        prompt = provider.poll()
        assert prompt is None

    @responses.activate
    def test_poll_sends_correct_request_body(self, base_url: str, poll_url: str):
        """Test poll sends correct assistant/plan in request."""
        def request_callback(request):
            body = json.loads(request.body)
            assert body["assistant_name"] == "ChatGPT"
            assert body["plan_name"] == "Plus"
            return (200, {}, json.dumps({
                "evaluation_id": None,
                "prompt_id": None,
                "prompt_text": None,
                "topic_id": None,
                "claimed_at": None
            }))

        responses.add_callback(
            responses.POST,
            poll_url,
            callback=request_callback
        )

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )
        provider.poll()

    @responses.activate
    def test_poll_retries_on_500_error(self, base_url: str, poll_url: str):
        """Test poll retries on 5xx server errors."""
        # First two attempts: 500 error
        responses.post(poll_url, status=500)
        responses.post(poll_url, status=500)
        # Third attempt: success
        responses.post(
            poll_url,
            json={
                "evaluation_id": None,
                "prompt_id": None,
                "prompt_text": None,
                "topic_id": None,
                "claimed_at": None
            },
            status=200
        )

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus",
            retry_attempts=3,
            retry_delay_seconds=0.1
        )

        prompt = provider.poll()
        assert prompt is None  # Success after retries

    @responses.activate
    def test_poll_fails_after_max_retries(self, base_url: str, poll_url: str):
        """Test poll raises error after max retries exhausted."""
        responses.post(poll_url, status=500)
        responses.post(poll_url, status=500)
        responses.post(poll_url, status=500)

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus",
            retry_attempts=3,
            retry_delay_seconds=0.1
        )

        with pytest.raises(ApiProviderError, match="server error"):
            provider.poll()

    @responses.activate
    def test_poll_does_not_retry_on_400_error(self, base_url: str, poll_url: str):
        """Test poll does not retry on 4xx client errors."""
        responses.post(poll_url, status=400)

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus",
            retry_attempts=3
        )

        with pytest.raises(ApiProviderError, match="rejected request"):
            provider.poll()

        # Should only make one request (no retries)
        assert len(responses.calls) == 1

    @responses.activate
    def test_poll_handles_timeout(self, base_url: str, poll_url: str):
        """Test poll handles timeout errors."""
        responses.post(poll_url, body=Timeout())

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus",
            retry_attempts=1
        )

        with pytest.raises(ApiProviderError, match="timed out"):
            provider.poll()

    @responses.activate
    def test_poll_handles_malformed_json(self, base_url: str, poll_url: str):
        """Test poll handles malformed JSON response."""
        responses.post(poll_url, body="not json", status=200)

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )

        with pytest.raises(ApiProviderError, match="malformed response"):
            provider.poll()

    @responses.activate
    def test_poll_handles_missing_fields(self, base_url: str, poll_url: str):
        """Test poll handles response with missing required fields."""
        responses.post(
            poll_url,
            json={"evaluation_id": 123},  # Missing prompt_id, prompt_text
            status=200
        )

        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )

        with pytest.raises(ApiProviderError, match="malformed"):
            provider.poll()

    def test_is_exhausted_always_false(self, base_url: str):
        """Test is_exhausted always returns False for API provider."""
        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )
        assert not provider.is_exhausted

    @responses.activate
    def test_context_manager(self, base_url: str, poll_url: str):
        """Test provider works as context manager."""
        responses.post(
            poll_url,
            json={
                "evaluation_id": None,
                "prompt_id": None,
                "prompt_text": None,
                "topic_id": None,
                "claimed_at": None
            },
            status=200
        )

        with HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        ) as provider:
            prompt = provider.poll()
            assert prompt is None

    def test_close_method(self, base_url: str):
        """Test close method releases resources."""
        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )
        provider.close()

        # Should not be able to poll after close
        with pytest.raises(ApiProviderError, match="closed"):
            provider.poll()

    def test_close_idempotent(self, base_url: str):
        """Test close can be called multiple times safely."""
        provider = HttpApiPromptProvider(
            api_base_url=base_url,
            assistant_name="ChatGPT",
            plan_name="Plus"
        )
        provider.close()
        provider.close()  # Should not raise
