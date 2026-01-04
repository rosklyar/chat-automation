"""Data models for the ChatGPT automation application."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


class PollingState(Enum):
    """State of the polling loop."""
    ACTIVE = auto()           # Processing prompts
    IDLE_NO_PROMPTS = auto()  # API reachable but queue empty
    DISCONNECTED = auto()     # API unreachable


@dataclass
class PollingConfig:
    """Configuration for polling backoff behavior."""
    base_interval: float = 5.0          # Starting interval (seconds)
    max_interval: float = 300.0         # Maximum interval (5 min cap)
    backoff_multiplier: float = 2.0     # Exponential growth factor
    api_error_interval: float = 300.0   # Fixed interval for API errors (5 min)
    browser_close_threshold: float = 60.0  # Close browser when wait > this


@dataclass(frozen=True)
class Citation:
    """A single citation/source from an AI response."""
    url: str
    text: str
    number: Optional[int] = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {"url": self.url, "text": self.text}


@dataclass
class EvaluationResult:
    """Result of evaluating a prompt through an AI assistant."""
    response_text: str
    citations: list[Citation] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.now)
    success: bool = True
    error_message: Optional[str] = None

    @property
    def has_citations(self) -> bool:
        """Check if this result contains valid citations."""
        return len(self.citations) > 0

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "response": self.response_text,
            "citations": [c.to_dict() for c in self.citations],
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class EvaluationRecorded:
    """Result of recording an evaluation with the session provider."""
    remaining: int
    rotated: bool

    @property
    def should_reset_bot(self) -> bool:
        """Convenience property - rotation means browser needs reset."""
        return self.rotated


@dataclass
class Prompt:
    """A prompt to be evaluated."""
    id: str
    text: str
    # Optional API metadata (for HTTP API provider)
    evaluation_id: Optional[int] = None
    topic_id: Optional[int] = None
    claimed_at: Optional[str] = None
