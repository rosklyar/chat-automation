"""Prompt provider abstraction for sourcing prompts from various sources."""

import logging
import sys
import time
from typing import Optional, Protocol, runtime_checkable

import requests
from requests.exceptions import RequestException, Timeout, HTTPError

from .models import Prompt

logger = logging.getLogger(__name__)


class PromptParseError(Exception):
    """Raised when prompt source data is malformed or invalid."""
    pass


class ApiProviderError(Exception):
    """Raised when API provider encounters errors."""

    def __init__(self, message: str, cause: Optional[Exception] = None) -> None:
        """
        Initialize API provider error.

        Args:
            message: Error description
            cause: Original exception that caused this error (if any)
        """
        super().__init__(message)
        self.cause = cause


@runtime_checkable
class PromptProvider(Protocol):
    """
    Protocol for providing prompts from various sources.

    Implementations can source prompts from CSV files, Kafka streams,
    databases, or any other source.
    """

    def poll(self) -> Optional[Prompt]:
        """
        Get the next prompt from the source.

        Returns:
            Next prompt if available, None if source is exhausted.
        """
        ...

    @property
    def is_exhausted(self) -> bool:
        """
        Check if the source has no more prompts available.

        Returns:
            True if no more prompts can be provided, False otherwise.
        """
        ...

    def close(self) -> None:
        """Release any resources (files, connections, etc.)."""
        ...

    def __enter__(self) -> "PromptProvider":
        """Context manager entry."""
        ...

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        ...


class HttpApiPromptProvider:
    """
    Provides prompts by polling an HTTP API endpoint.

    Continuously polls POST /evaluations/api/v1/poll endpoint.
    Returns None when no prompts available (non-blocking).
    Never exhausts - is_exhausted always returns False.

    Request format:
        {"assistant_name": "ChatGPT", "plan_name": "Plus"}

    Response format (prompt available):
        {
            "evaluation_id": 123,
            "prompt_id": 456,
            "prompt_text": "...",
            "topic_id": 1,
            "claimed_at": "2025-12-09T10:30:00Z"
        }

    Response format (no prompts):
        {
            "evaluation_id": null,
            "prompt_id": null,
            "prompt_text": null,
            "topic_id": null,
            "claimed_at": null
        }
    """

    def __init__(
        self,
        api_base_url: str,
        assistant_name: str,
        plan_name: str,
        timeout_seconds: float = 30.0,
        retry_attempts: int = 3,
        retry_delay_seconds: float = 1.0
    ) -> None:
        """
        Initialize HTTP API prompt provider.

        Args:
            api_base_url: Base API URL (e.g., "https://api.example.com")
            assistant_name: Assistant name for requests (e.g., "ChatGPT")
            plan_name: Plan name for requests (e.g., "Plus")
            timeout_seconds: Request timeout in seconds
            retry_attempts: Max attempts for transient failures
            retry_delay_seconds: Delay between retries

        Raises:
            ValueError: If api_base_url is invalid or empty
        """
        # Validate inputs
        if not api_base_url or not api_base_url.strip():
            raise ValueError("api_base_url cannot be empty")

        if not assistant_name or not plan_name:
            raise ValueError("assistant_name and plan_name are required")

        # Normalize URL (remove trailing slash)
        self._api_base_url = api_base_url.rstrip('/')
        self._poll_endpoint = f"{self._api_base_url}/evaluations/api/v1/poll"

        self._assistant_name = assistant_name
        self._plan_name = plan_name
        self._timeout = timeout_seconds
        self._retry_attempts = retry_attempts
        self._retry_delay = retry_delay_seconds

        # Create persistent session for connection pooling
        self._session = requests.Session()
        self._session.headers.update({
            'Content-Type': 'application/json',
            'Accept': 'application/json'
        })

        self._closed = False

        logger.info(
            f"Initialized HTTP API provider: {self._poll_endpoint} "
            f"(assistant={assistant_name}, plan={plan_name})"
        )

    def poll(self) -> Optional[Prompt]:
        """
        Poll API for next prompt.

        Makes POST request to /evaluations/api/v1/poll with assistant/plan info.
        Retries transient failures automatically.

        Returns:
            Prompt with evaluation metadata if available, None if no prompts queued.

        Raises:
            ApiProviderError: If API returns error or persistent failures occur
        """
        if self._closed:
            raise ApiProviderError("Cannot poll from closed provider")

        request_body = {
            "assistant_name": self._assistant_name,
            "plan_name": self._plan_name
        }

        # Retry logic for transient failures
        for attempt in range(1, self._retry_attempts + 1):
            try:
                response = self._session.post(
                    self._poll_endpoint,
                    json=request_body,
                    timeout=self._timeout
                )

                # Check HTTP status
                response.raise_for_status()

                # Parse response - catch JSON errors before other exceptions
                try:
                    data = response.json()
                except ValueError as e:
                    # JSON decode errors
                    logger.error(f"Invalid API response format (invalid JSON): {e}")
                    raise ApiProviderError(
                        f"API returned malformed response: {e}",
                        cause=e
                    )

                # Validate required fields exist
                if 'prompt_id' not in data or 'prompt_text' not in data:
                    logger.error("API response missing required fields (prompt_id, prompt_text)")
                    raise ApiProviderError(
                        "API returned malformed response: missing required fields"
                    )

                # Check if response has prompt (non-null fields)
                if data.get('prompt_id') is None:
                    # Empty response - no prompts available
                    logger.debug("API returned no prompts (empty response)")
                    return None

                # Valid prompt received
                prompt = Prompt(
                    id=str(data['prompt_id']),
                    text=data['prompt_text'],
                    evaluation_id=data.get('evaluation_id'),
                    topic_id=data.get('topic_id'),
                    claimed_at=data.get('claimed_at')
                )

                logger.info(
                    f"Received prompt from API: id={prompt.id}, "
                    f"evaluation_id={prompt.evaluation_id}"
                )
                return prompt

            except Timeout:
                logger.warning(
                    f"Request timeout (attempt {attempt}/{self._retry_attempts}): "
                    f"{self._poll_endpoint}"
                )
                if attempt < self._retry_attempts:
                    time.sleep(self._retry_delay)
                    continue
                raise ApiProviderError(
                    f"API request timed out after {self._retry_attempts} attempts",
                    cause=sys.exc_info()[1]
                )

            except ApiProviderError:
                # Re-raise our own errors (from JSON parsing or validation)
                raise

            except HTTPError as e:
                # 4xx/5xx errors
                status_code = e.response.status_code if hasattr(e, 'response') and e.response else None

                # If we can't get status code from exception, try to parse from message
                if status_code is None and hasattr(e, 'args') and e.args:
                    # Try to extract status from error message (e.g., "400 Client Error: ...")
                    try:
                        msg = str(e.args[0])
                        if msg and msg[0:3].isdigit():
                            status_code = int(msg[0:3])
                    except (ValueError, IndexError):
                        pass

                logger.error(
                    f"HTTP error {status_code}: {e}"
                )
                # Don't retry 4xx client errors (bad request, auth, etc)
                if status_code and 400 <= status_code < 500:
                    raise ApiProviderError(
                        f"API rejected request (HTTP {status_code})",
                        cause=e
                    )
                # Retry 5xx server errors
                if attempt < self._retry_attempts:
                    logger.warning(f"Retrying after server error (attempt {attempt})")
                    time.sleep(self._retry_delay)
                    continue
                raise ApiProviderError(
                    f"API server error after {self._retry_attempts} attempts",
                    cause=e
                )

            except RequestException as e:
                # Network errors, connection errors
                logger.warning(
                    f"Network error (attempt {attempt}/{self._retry_attempts}): {e}"
                )
                if attempt < self._retry_attempts:
                    time.sleep(self._retry_delay)
                    continue
                raise ApiProviderError(
                    f"Network error after {self._retry_attempts} attempts",
                    cause=e
                )

    @property
    def is_exhausted(self) -> bool:
        """
        Check if provider has no more prompts.

        For API provider, always returns False (continuous polling).
        When no prompts available, poll() returns None temporarily.
        """
        return False

    def close(self) -> None:
        """
        Release HTTP session resources.

        Safe to call multiple times. After close(), poll() will raise.
        """
        if not self._closed:
            self._session.close()
            self._closed = True
            logger.debug("Closed HTTP API provider session")

    def __enter__(self) -> "HttpApiPromptProvider":
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit - cleanup resources."""
        self.close()


__all__ = [
    'PromptProvider',
    'HttpApiPromptProvider',
    'PromptParseError',
    'ApiProviderError'
]
