"""Data models for the ChatGPT automation application."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


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
