"""ChatGPT automation package."""

from .models import (
    SessionType,
    Citation,
    EvaluationResult,
    Prompt,
    SessionInfo,
)
from .session_provider import SessionProvider, FileSessionProvider
from .bot_interface import Bot, BotFactory
from .chatgpt import ChatGPTBot, ChatGPTBotFactory

__all__ = [
    # Models
    "SessionType",
    "Citation",
    "EvaluationResult",
    "Prompt",
    "SessionInfo",
    # Session Provider
    "SessionProvider",
    "FileSessionProvider",
    # Bot Interface
    "Bot",
    "BotFactory",
    # ChatGPT Implementation
    "ChatGPTBot",
    "ChatGPTBotFactory",
]
