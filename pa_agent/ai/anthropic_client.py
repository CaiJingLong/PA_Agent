"""Anthropic native Messages API client for PA Agent.

Implements the same interface as :class:`pa_agent.ai.deepseek_client.DeepSeekClient`
for orchestrators: ``stream_chat()`` and ``update_provider()``.

Uses the official ``anthropic`` SDK and the Messages API directly (no OpenAI
compatibility shim). System turns are hoisted to the top-level ``system``
parameter; thinking is mapped via ``thinking={"type": "enabled"|"adaptive", ...}``.
"""

from __future__ import annotations

import contextlib
import logging
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pa_agent.ai.anthropic_connector import resolve_anthropic_model_id
from pa_agent.ai.deepseek_client import (
    AIReply,
    AIUsage,
    CancelledError,
    _completion_max_tokens,
    _effort_budget_tokens,
    _model_uses_claude_adaptive,
    _PRACTICAL_UNLIMITED_MAX_TOKENS,
)
from pa_agent.config.settings import AIProviderSettings
from pa_agent.util.mask_secret import mask_secret

if TYPE_CHECKING:
    from pa_agent.util.threading import CancelToken

try:
    from anthropic import Anthropic as _Anthropic  # type: ignore[import]
except ImportError as _exc:
    _Anthropic = None  # type: ignore[assignment,misc]
    _ANTHROPIC_IMPORT_ERROR = _exc
else:
    _ANTHROPIC_IMPORT_ERROR = None

logger = logging.getLogger(__name__)


def _hoist_system(messages: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], str | None]:
    """Split system turns out of *messages* for the Anthropic Messages API.

    Anthropic does not allow ``role=system`` inside ``messages``; system text
    must be passed via the top-level ``system`` parameter. Consecutive system
    turns are joined with blank lines.
    """
    system_parts: list[str] = []
    api_messages: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        if role == "system":
            content = msg.get("content", "")
            if content:
                system_parts.append(str(content))
        else:
            api_messages.append(msg)
    system_param = "\n\n".join(system_parts) if system_parts else None
    return api_messages, system_param


def _resolve_thinking_config(
    settings: AIProviderSettings,
    *,
    thinking: bool | None,
    reasoning_effort: str | None,
    max_output: int,
) -> dict[str, Any] | None:
    """Build the Anthropic ``thinking`` config dict, or None when disabled."""
    _thinking = thinking if thinking is not None else settings.thinking
    if not _thinking:
        return None
    model = resolve_anthropic_model_id(settings.model)
    if _model_uses_claude_adaptive(model):
        # Opus 4.7+ uses adaptive thinking; effort carried via output_config-like hint.
        # Anthropic native API does not accept output_config; effort is informational only.
        return {"type": "adaptive"}
    budget = _effort_budget_tokens(reasoning_effort, max_output=max_output)
    return {"type": "enabled", "budget_tokens": budget}


class AnthropicClient:
    """Thin wrapper around the Anthropic native Messages API."""

    def __init__(self, settings: AIProviderSettings, logger_: logging.Logger | None = None) -> None:
        self._settings = settings
        self._log = logger_ or logger

    def update_provider(self, settings: AIProviderSettings) -> None:
        """Replace in-memory provider settings (e.g. after auto-fallback)."""
        self._settings = settings

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        *,
        on_reasoning_token: Callable[[str], None] | None = None,
        on_content_token: Callable[[str], None] | None = None,
        thinking: bool | None = None,
        reasoning_effort: str | None = None,
        cancel_token: CancelToken | None = None,
        timeout_s: float = 600.0,
    ) -> AIReply:
        """Stream *messages* to the Anthropic Messages API, calling callbacks per token.

        ``thinking_delta`` events map to ``on_reasoning_token``;
        ``text_delta`` events map to ``on_content_token``.
        """
        if cancel_token is not None and cancel_token.is_set():
            raise CancelledError("Request cancelled before API call")

        if _Anthropic is None:
            raise RuntimeError(
                "anthropic package is not installed"
            ) from _ANTHROPIC_IMPORT_ERROR

        api_messages, system_param = _hoist_system(messages)
        model_id = resolve_anthropic_model_id(self._settings.model)
        max_tokens = _completion_max_tokens(
            self._settings, extra_body={}, effort=reasoning_effort
        )
        # Anthropic requires max_tokens <= model output cap; clamp to practical ceiling.
        max_tokens = min(max_tokens, _PRACTICAL_UNLIMITED_MAX_TOKENS)
        thinking_config = _resolve_thinking_config(
            self._settings,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            max_output=max_tokens,
        )

        masked_key = mask_secret(self._settings.api_key)
        self._log.info(
            "AnthropicClient.stream_chat: model=%s thinking=%s effort=%s "
            "max_tokens=%s system_hoisted=%s key=...%s msgs=%d",
            model_id,
            thinking_config is not None,
            reasoning_effort,
            max_tokens,
            bool(system_param),
            masked_key[-4:] if len(masked_key) >= 4 else "****",
            len(api_messages),
        )

        client_kwargs: dict[str, Any] = {"api_key": self._settings.api_key}
        if self._settings.base_url:
            client_kwargs["base_url"] = self._settings.base_url
        client = _Anthropic(**client_kwargs)

        t0 = time.monotonic()
        reasoning_content = ""
        content = ""
        request_id = ""
        prompt_tokens = 0
        completion_tokens = 0
        total_tokens = 0
        cached_tokens = 0

        request_kwargs: dict[str, Any] = {
            "model": model_id,
            "messages": api_messages,
            "max_tokens": max_tokens,
            "timeout": timeout_s,
        }
        if system_param:
            request_kwargs["system"] = system_param
        if thinking_config is not None:
            request_kwargs["thinking"] = thinking_config

        try:
            with client.messages.stream(**request_kwargs) as stream:
                for event in stream:
                    if cancel_token is not None and cancel_token.is_set():
                        with contextlib.suppress(Exception):
                            stream.close()
                        raise CancelledError("Request cancelled during Anthropic stream")

                    etype = getattr(event, "type", "")

                    if etype == "message_start":
                        msg = getattr(event, "message", None)
                        if msg is not None:
                            request_id = request_id or (getattr(msg, "id", "") or "")

                    elif etype == "content_block_start":
                        # Track block type for routing deltas; block.index used for ordering.
                        pass

                    elif etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        dtype = getattr(delta, "type", "")
                        if dtype == "thinking_delta":
                            chunk = getattr(delta, "thinking", "") or ""
                            if chunk:
                                reasoning_content += chunk
                                if on_reasoning_token is not None:
                                    on_reasoning_token(chunk)
                        elif dtype == "text_delta":
                            chunk = getattr(delta, "text", "") or ""
                            if chunk:
                                content += chunk
                                if on_content_token is not None:
                                    on_content_token(chunk)

                    elif etype == "message_delta":
                        usage = getattr(event, "usage", None)
                        if usage is not None:
                            out_tok = getattr(usage, "output_tokens", None)
                            if out_tok is not None:
                                completion_tokens = out_tok or completion_tokens

                    elif etype == "message_stop":
                        final_msg = stream.get_final_message()
                        usage = getattr(final_msg, "usage", None)
                        if usage is not None:
                            prompt_tokens = getattr(usage, "input_tokens", 0) or prompt_tokens
                            out_tok = getattr(usage, "output_tokens", 0)
                            if out_tok:
                                completion_tokens = out_tok
                            # Anthropic prompt caching: cache_read_input_tokens
                            cached = getattr(usage, "cache_read_input_tokens", 0) or 0
                            cached_tokens = cached or cached_tokens
                        request_id = request_id or (getattr(final_msg, "id", "") or "")
                        model_id = getattr(final_msg, "model", "") or model_id

        except CancelledError:
            raise
        except Exception as exc:
            latency_ms = (time.monotonic() - t0) * 1000
            self._log.error("AnthropicClient stream error after %.0f ms: %s", latency_ms, exc)
            raise

        latency_ms = (time.monotonic() - t0) * 1000
        total_tokens = prompt_tokens + completion_tokens

        usage = AIUsage(
            prompt_tokens=prompt_tokens,
            cached_prompt_tokens=cached_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
        )

        raw: dict[str, Any] = {
            "id": request_id,
            "model": model_id,
            "content": content,
            "reasoning_content": reasoning_content,
            "usage": {
                "prompt_tokens": usage.prompt_tokens,
                "cached_prompt_tokens": usage.cached_prompt_tokens,
                "cache_miss_tokens": usage.cache_miss_tokens,
                "cache_hit_rate_pct": round(usage.cache_hit_rate * 100, 1),
                "completion_tokens": usage.completion_tokens,
                "total_tokens": usage.total_tokens,
            },
            "latency_ms": latency_ms,
        }

        self._log.info(
            "AnthropicClient.stream_chat done: latency=%.0f ms "
            "reasoning_chars=%d content_chars=%d thinking=%s",
            latency_ms,
            len(reasoning_content),
            len(content),
            thinking_config is not None,
        )

        if not content.strip():
            self._log.warning(
                "Anthropic API returned empty content (model=%s base_url=%s).",
                self._settings.model,
                self._settings.base_url,
            )

        return AIReply(
            content=content,
            reasoning_content=reasoning_content,
            raw=raw,
            usage=usage,
            request_id=request_id,
            latency_ms=latency_ms,
        )
