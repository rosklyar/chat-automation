"""ChatGPT automation package."""

from .models import (
    Citation,
    EvaluationResult,
    Prompt,
)
from .session_provider import SessionProvider, FileSessionProvider
from .bot_interface import Bot, BotFactory
from .chatgpt import ChatGPTBot, ChatGPTBotFactory
from .prompt_provider import (
    PromptProvider,
    HttpApiPromptProvider,
    PromptParseError,
    ApiProviderError,
)
from .result_persister import (
    ResultPersister,
    HttpApiResultPersister,
    PersistenceError,
)
from .shutdown_handler import ShutdownHandler

__all__ = [
    # Models
    "Citation",
    "EvaluationResult",
    "Prompt",
    # Session Provider
    "SessionProvider",
    "FileSessionProvider",
    # Bot Interface
    "Bot",
    "BotFactory",
    # ChatGPT Implementation
    "ChatGPTBot",
    "ChatGPTBotFactory",
    # Prompt Provider
    "PromptProvider",
    "HttpApiPromptProvider",
    "PromptParseError",
    "ApiProviderError",
    # Result Persister
    "ResultPersister",
    "HttpApiResultPersister",
    "PersistenceError",
    # Shutdown Handler
    "ShutdownHandler",
]
