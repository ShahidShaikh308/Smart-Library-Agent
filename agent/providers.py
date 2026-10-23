"""Provider factory and bounded retry/failover for chat model requests."""

from __future__ import annotations

import json
import logging
import math
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from langchain_core.messages import BaseMessage
from pydantic import SecretStr

from agent.orchestrator_errors import ProviderRequestError

logger = logging.getLogger(__name__)
TRANSIENT_STATUSES = {429, 503, 504}
ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _serialized_messages_for_debug(messages: list[BaseMessage]) -> str:
    """Serialize the exact OpenAI-compatible message shape for diagnostics."""
    try:
        # ChatOpenAI (used for OpenRouter) uses this conversion before sending
        # chat-completion requests. Keep the private import debug-only so the
        # normal provider path remains independent of this diagnostic helper.
        from langchain_openai.chat_models.base import _convert_message_to_dict

        payload = [_convert_message_to_dict(message) for message in messages]
    except (ImportError, AttributeError, TypeError, ValueError):
        payload = [message.model_dump(mode="json") for message in messages]
    return json.dumps(payload, ensure_ascii=False, default=str)


def _response_body(error: Exception) -> str | None:
    """Return the untruncated HTTP response body when the SDK exposes it."""
    response = getattr(error, "response", None)
    if response is not None:
        try:
            body = response.text
            if body:
                return str(body)
        except (AttributeError, OSError, RuntimeError, UnicodeDecodeError, ValueError):
            logger.debug("Could not read OpenRouter response.text", exc_info=True)
        try:
            content = response.content
            if content:
                return content.decode("utf-8", errors="replace")
        except (AttributeError, OSError, RuntimeError, UnicodeDecodeError, ValueError):
            logger.debug("Could not read OpenRouter response.content", exc_info=True)
    body = getattr(error, "body", None)
    return None if body is None else json.dumps(body, ensure_ascii=False, default=str)


@dataclass(frozen=True)
class ModelRoute:
    provider: str
    model_name: str
    model: Any


def _truthy(value: str | None) -> bool:
    return (value or "").strip().casefold() in {"1", "true", "yes", "on"}


def _required_key(*names: str) -> str:
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    raise ProviderRequestError(f"Missing API key. Set {names[0]} in your .env file.")


def _float_setting(name: str, default: float, minimum: float, maximum: float) -> float:
    """Parse a bounded numeric setting without failing application startup."""
    raw = os.getenv(name, str(default))
    try:
        value = float(raw)
        if not math.isfinite(value):
            raise ValueError("setting must be finite")
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %.2f", name, raw, default)
        return default
    bounded = min(maximum, max(minimum, value))
    if bounded != value:
        logger.warning("Out-of-range %s=%r; clamped to %.2f", name, raw, bounded)
    return bounded


def _retry_count() -> int:
    raw = os.getenv("LLM_RETRIES", "2")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("Invalid LLM_RETRIES=%r; using default 2", raw)
        return 2
    bounded = min(5, max(0, value))
    if bounded != value:
        logger.warning("Out-of-range LLM_RETRIES=%r; clamped to %d", raw, bounded)
    return bounded


def _provider_model(provider: str, model_name: str):
    if provider == "openrouter":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=SecretStr(_required_key("OPENROUTER_API_KEY")),
            base_url=os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1"),
            model=model_name,
            default_headers={
                "HTTP-Referer": os.getenv("OPENROUTER_SITE_URL", "http://localhost"),
                "X-Title": os.getenv("OPENROUTER_APP_NAME", "Smart Library Agent"),
            },
            temperature=0,
            timeout=_float_setting("LLM_TIMEOUT_SECONDS", 60.0, 1.0, 600.0),
            max_retries=0,
        )
    if provider == "openai":
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            api_key=SecretStr(_required_key("OPENAI_API_KEY")),
            model=model_name,
            temperature=0,
            timeout=_float_setting("LLM_TIMEOUT_SECONDS", 60.0, 1.0, 600.0),
            max_retries=0,
        )
    if provider == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model_name,
            api_key=SecretStr(_required_key("GOOGLE_API_KEY", "GEMINI_API_KEY")),
            vertexai=False,
            timeout=_float_setting("LLM_TIMEOUT_SECONDS", 60.0, 1.0, 600.0),
            max_retries=0,
        )
    if provider == "groq":
        from langchain_groq import ChatGroq

        return ChatGroq(
            model=model_name,
            api_key=SecretStr(_required_key("GROQ_API_KEY")),
            temperature=0,
            timeout=_float_setting("LLM_TIMEOUT_SECONDS", 60.0, 1.0, 600.0),
            max_retries=0,
        )
    if provider == "ollama":
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=model_name,
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            temperature=0,
            client_kwargs={
                "timeout": _float_setting("LLM_TIMEOUT_SECONDS", 60.0, 1.0, 600.0)
            },
        )
    raise ProviderRequestError(
        "Unsupported LLM_PROVIDER. Choose openrouter, openai, gemini, groq, or ollama."
    )


def _status_code(error: Exception) -> int | None:
    for value in (
        getattr(error, "status_code", None),
        getattr(error, "status", None),
        getattr(getattr(error, "response", None), "status_code", None),
        getattr(getattr(error, "response", None), "status", None),
    ):
        try:
            if value is not None:
                return int(value)
        except (TypeError, ValueError):
            continue
    return None


def _retryable(error: Exception) -> bool:
    status = _status_code(error)
    name = type(error).__name__.casefold()
    return status in TRANSIENT_STATUSES or any(
        token in name for token in ("timeout", "connection", "temporarilyunavailable")
    )


class ModelRouter:
    """Invoke configured model routes with bounded retry and optional fallback."""

    def __init__(
        self,
        routes: list[ModelRoute],
        tools: list[Any],
        retries: int = 2,
        backoff_seconds: float = 1.0,
        max_backoff_seconds: float = 8.0,
    ) -> None:
        if not routes:
            raise ProviderRequestError("No LLM model is configured.")
        self.routes = routes
        self.tools = tools
        self.retries = max(0, retries)
        self.backoff_seconds = max(0.0, backoff_seconds)
        self.max_backoff_seconds = max(0.0, max_backoff_seconds)

    def invoke(self, messages: list[BaseMessage], *, allow_tools: bool = True):
        last_error: Exception | None = None
        for route_index, route in enumerate(self.routes):
            model = route.model.bind_tools(self.tools) if allow_tools else route.model
            for attempt in range(self.retries + 1):
                try:
                    logger.debug(
                        "LLM request provider=%s model=%s attempt=%s allow_tools=%s serialized_messages=%s",
                        route.provider,
                        route.model_name,
                        attempt + 1,
                        allow_tools,
                        _serialized_messages_for_debug(messages),
                    )
                    response = model.invoke(messages)
                    logger.debug(
                        "LLM response provider=%s model=%s",
                        route.provider,
                        route.model_name,
                    )
                    return response
                except Exception as error:
                    last_error = error
                    status = _status_code(error)
                    retryable = _retryable(error)
                    can_retry = retryable and attempt < self.retries
                    can_fallback = retryable and route_index < len(self.routes) - 1
                    logger.warning(
                        "LLM request failed provider=%s model=%s status=%s attempt=%s retryable=%s",
                        route.provider,
                        route.model_name,
                        status,
                        attempt + 1,
                        retryable,
                    )
                    if route.provider == "openrouter":
                        logger.debug(
                            "OpenRouter error response provider=%s model=%s status=%s body=%s",
                            route.provider,
                            route.model_name,
                            status,
                            _response_body(error),
                        )
                    if can_retry:
                        delay = min(
                            self.backoff_seconds * (2**attempt),
                            self.max_backoff_seconds,
                        )
                        logger.info("Retrying LLM request in %.2f seconds", delay)
                        time.sleep(delay)
                        continue
                    if can_fallback:
                        logger.warning(
                            "Failing over from %s:%s to %s:%s",
                            route.provider,
                            route.model_name,
                            self.routes[route_index + 1].provider,
                            self.routes[route_index + 1].model_name,
                        )
                        break
                    raise ProviderRequestError(
                        _friendly_provider_error(error, status)
                    ) from error
        raise ProviderRequestError(
            _friendly_provider_error(
                last_error, _status_code(last_error) if last_error else None
            )
        ) from last_error


def _friendly_provider_error(error: Exception | None, status: int | None) -> str:
    if status == 429:
        return "The AI service is rate-limited right now. Please try again shortly."
    if status in {503, 504}:
        return "The AI service is temporarily unavailable. Please try again shortly."
    if status in {401, 403}:
        return "The AI provider rejected the configured credentials. Check the API key in your .env file."
    if status == 404:
        return "The configured AI model was not found by the provider. Check LLM_MODEL in your .env file."
    if status == 400:
        return "The AI provider rejected the request. Check the selected model and provider settings."
    if error is None or _retryable(error):
        return "I could not reach the AI service. Check your connection and try again."
    return "The AI service could not complete that request. Check your provider and model settings."


def create_model_router(tools: list[Any]) -> ModelRouter:
    """Build configured provider and model routes from environment settings."""
    load_dotenv(ENV_FILE, override=True)
    debug = _truthy(os.getenv("AGENT_DEBUG"))
    logger.setLevel(logging.DEBUG if debug else logging.INFO)
    provider = (os.getenv("LLM_PROVIDER", "openrouter").strip() or "openrouter").casefold()
    defaults = {
        "openrouter": "cohere/north-mini-code:free",
        "openai": "gpt-4o-mini",
        "gemini": "gemini-3.8-flash",
        "groq": "openai/gpt-oss-120b",
        "ollama": "llama3.1:8b",
    }
    if provider not in defaults:
        raise ProviderRequestError(
            "Unsupported LLM_PROVIDER. Choose openrouter, openai, gemini, groq, or ollama."
        )
    primary = os.getenv("LLM_MODEL", "").strip() or defaults[provider]
    fallback_setting = os.getenv(
        "OPENROUTER_FALLBACK_MODELS"
        if provider == "openrouter"
        else "LLM_FALLBACK_MODELS",
        "",
    )
    model_names = [primary] + [
        name.strip() for name in fallback_setting.split(",") if name.strip()
    ]
    deduplicated = list(dict.fromkeys(model_names))
    routes = [
        ModelRoute(provider, name, _provider_model(provider, name))
        for name in deduplicated
    ]
    logger.info("LLM provider selected provider=%s models=%s", provider, deduplicated)
    return ModelRouter(
        routes,
        tools,
        retries=_retry_count(),
        backoff_seconds=_float_setting("LLM_RETRY_BASE_SECONDS", 1.0, 0.0, 60.0),
        max_backoff_seconds=_float_setting("LLM_RETRY_MAX_SECONDS", 8.0, 0.0, 120.0),
    )
