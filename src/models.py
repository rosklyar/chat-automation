"""Data models for the ChatGPT automation application."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Optional


class SessionType(Enum):
    """Supported AI provider session types."""
    CHATGPT = auto()
    # Future: CLAUDE = auto()
    # Future: GEMINI = auto()


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


@dataclass
class Prompt:
    """A prompt to be evaluated."""
    id: str
    text: str


@dataclass
class SessionInfo:
    """Information about a managed session."""
    session_id: str
    session_type: SessionType
    file_path: str
    usage_count: int = 0
    max_usage: int = 10
    is_valid: bool = True

    @property
    def evaluations_remaining(self) -> int:
        """Number of evaluations left before rotation needed."""
        return max(0, self.max_usage - self.usage_count)

    @property
    def needs_rotation(self) -> bool:
        """Check if this session has exhausted its usage limit."""
        return self.usage_count >= self.max_usage
