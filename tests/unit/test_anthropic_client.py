"""Unit tests for AnthropicClient and anthropic_connector routing."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from pa_agent.ai.anthropic_client import AnthropicClient, _hoist_system
from pa_agent.ai.anthropic_connector import (
    _ANTHROPIC_DEFAULT_MODEL_ID,
    apply_anthropic_provider_to_settings,
    is_anthropic_native_model,
    resolve_anthropic_model_id,
    should_use_anthropic_provider,
)
from pa_agent.ai.deepseek_client import CancelledError
from pa_agent.config.settings import AIProviderSettings


def _make_settings(
    model: str = "anthropic/claude-sonnet-4-5",
    api_key: str = "sk-ant-test1234",
    base_url: str = "",
    thinking: bool = True,
    provider_type: str = "auto",
) -> AIProviderSettings:
    s = AIProviderSettings()
    s.model = model
    s.api_key = api_key
    s.base_url = base_url
    s.thinking = thinking
    s.provider_type = provider_type  # type: ignore[assignment]
    return s


# ── connector ─────────────────────────────────────────────────────────────────


def test_is_anthropic_native_model_alias():
    assert is_anthropic_native_model("anthropic")
    assert is_anthropic_native_model("anthropic/claude-sonnet-4-5")
    assert is_anthropic_native_model("Anthropic/claude-opus-5")


def test_is_anthropic_native_model_rejects_non_alias():
    assert not is_anthropic_native_model("claude-sonnet-4-5")
    assert not is_anthropic_native_model("openclaw_cs")
    assert not is_anthropic_native_model("")
    assert not is_anthropic_native_model(None)


def test_resolve_anthropic_model_id_with_suffix():
    assert resolve_anthropic_model_id("anthropic/claude-sonnet-4-5") == "claude-sonnet-4-5"


def test_resolve_anthropic_model_id_bare_alias_uses_default():
    assert resolve_anthropic_model_id("anthropic") == _ANTHROPIC_DEFAULT_MODEL_ID


def test_resolve_anthropic_model_id_non_alias_returns_default():
    assert resolve_anthropic_model_id("claude-sonnet-4-5") == _ANTHROPIC_DEFAULT_MODEL_ID


def test_should_use_anthropic_provider_ignores_base_url():
    assert should_use_anthropic_provider("anthropic", "")
    assert should_use_anthropic_provider("anthropic/claude-opus-5", "https://api.anthropic.com")
    assert not should_use_anthropic_provider("deepseek-chat", "")


def test_apply_anthropic_provider_to_settings_requires_api_key():
    settings = _make_settings(api_key="")
    err = apply_anthropic_provider_to_settings(settings, preferred_model="anthropic/claude-opus-5")
    assert err is not None
    assert "API Key" in err


def test_apply_anthropic_provider_to_settings_success_preserves_alias():
    settings = _make_settings(api_key="sk-ant-xxx")
    err = apply_anthropic_provider_to_settings(settings, preferred_model="anthropic/claude-sonnet-4-5")
    assert err is None
    assert settings.provider.model == "anthropic/claude-sonnet-4-5"
    assert settings.provider.api_key == "sk-ant-xxx"


# ─_hoist_system ────────────────────────────────────────────────────────────────


def test_apply_anthropic_provider_to_settings_requires_api_key():
    from pa_agent.config.settings import Settings

    s = Settings()
    s.provider.model = "anthropic/claude-opus-5"
    s.provider.api_key = ""
    err = apply_anthropic_provider_to_settings(s, preferred_model="anthropic/claude-opus-5")
    assert err is not None
    assert "API Key" in err


def test_apply_anthropic_provider_to_settings_success_preserves_alias():
    from pa_agent.config.settings import Settings

    s = Settings()
    s.provider.api_key = "sk-ant-xxx"
    err = apply_anthropic_provider_to_settings(s, preferred_model="anthropic/claude-sonnet-4-5")
    assert err is None
    assert s.provider.model == "anthropic/claude-sonnet-4-5"
    assert s.provider.api_key == "sk-ant-xxx"

def test_hoist_system_no_system_returns_none():
    messages = [{"role": "user", "content": "Hello"}]
    api_messages, system_param = _hoist_system(messages)
    assert system_param is None
    assert api_messages == messages


def test_hoist_system_empty_system_content_skipped():
    messages = [
        {"role": "system", "content": ""},
        {"role": "user", "content": "Hello"},
    ]
    api_messages, system_param = _hoist_system(messages)
    assert system_param is None
    assert len(api_messages) == 1


# ── AnthropicClient.stream_chat ───────────────────────────────────────────────


def _make_stream_event(etype: str, **kwargs) -> MagicMock:
    ev = MagicMock()
    ev.type = etype
    for k, v in kwargs.items():
        setattr(ev, k, v)
    return ev


def _make_delta_event(dtype: str, **fields) -> MagicMock:
    delta = MagicMock()
    delta.type = dtype
    for k, v in fields.items():
        setattr(delta, k, v)
    ev = MagicMock()
    ev.type = "content_block_delta"
    ev.delta = delta
    return ev

def _make_stream_ctx(events, final_msg):
    """Build a mock that works as `with client.messages.stream(...) as stream:`.

    `stream` must be iterable (yields events) AND expose `get_final_message()`.
    """
    ctx = MagicMock()
    ctx.__enter__.return_value = ctx
    ctx.__exit__.return_value = False
    ctx.__iter__ = lambda self: iter(events)
    ctx.get_final_message.return_value = final_msg
    return ctx


def _make_final_message(
    *,
    msg_id: str = "msg_abc",
    model: str = "claude-sonnet-4-5",
    input_tokens: int = 100,
    output_tokens: int = 50,
    cache_read: int = 0,
) -> MagicMock:
    usage = MagicMock()
    usage.input_tokens = input_tokens
    usage.output_tokens = output_tokens
    usage.cache_read_input_tokens = cache_read
    msg = MagicMock()
    msg.id = msg_id
    msg.model = model
    msg.usage = usage
    return msg


def test_stream_chat_thinking_and_text_callbacks():
    """thinking_delta -> on_reasoning_token; text_delta -> on_content_token."""
    settings = _make_settings(model="anthropic/claude-sonnet-4-5", thinking=True)

    events = [
        _make_stream_event("message_start", message=MagicMock(id="msg_abc")),
        _make_delta_event("thinking_delta", thinking="reasoning chunk "),
        _make_delta_event("text_delta", text="answer chunk "),
        _make_stream_event("message_stop"),
    ]
    final_msg = _make_final_message()

    stream_ctx = _make_stream_ctx(events, final_msg)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    with patch("pa_agent.ai.anthropic_client._Anthropic", lambda **kw: mock_client):
        client = AnthropicClient(settings)
        reasoning_tokens: list[str] = []
        content_tokens: list[str] = []
        reply = client.stream_chat(
            [{"role": "user", "content": "hi"}],
            on_reasoning_token=reasoning_tokens.append,
            on_content_token=content_tokens.append,
        )

    assert reasoning_tokens == ["reasoning chunk "]
    assert content_tokens == ["answer chunk "]
    assert reply.content == "answer chunk "
    assert reply.reasoning_content == "reasoning chunk "
    assert reply.request_id == "msg_abc"
    assert reply.usage.prompt_tokens == 100
    assert reply.usage.completion_tokens == 50
    assert reply.usage.total_tokens == 150


def test_stream_chat_system_hoisted_to_system_param():
    """System turns must be passed via the `system` kwarg, not in messages."""
    settings = _make_settings(model="anthropic/claude-sonnet-4-5", thinking=False)

    events = [_make_stream_event("message_stop")]
    final_msg = _make_final_message()

    stream_ctx = _make_stream_ctx(events, final_msg)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    with patch("pa_agent.ai.anthropic_client._Anthropic", lambda **kw: mock_client):
        client = AnthropicClient(settings)
        client.stream_chat(
            [
                {"role": "system", "content": "SYS"},
                {"role": "user", "content": "hi"},
            ],
        )

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    assert call_kwargs["system"] == "SYS"
    assert all(m["role"] != "system" for m in call_kwargs["messages"])


def test_stream_chat_cancel_before_call_raises():
    settings = _make_settings()
    cancel_token = MagicMock()
    cancel_token.is_set.return_value = True

    client = AnthropicClient(settings)
    with pytest.raises(CancelledError):
        client.stream_chat([{"role": "user", "content": "hi"}], cancel_token=cancel_token)


def test_stream_chat_thinking_config_emitted_when_enabled():
    settings = _make_settings(model="anthropic/claude-sonnet-4-5", thinking=True)

    events = [_make_stream_event("message_stop")]
    final_msg = _make_final_message()
    stream_ctx = _make_stream_ctx(events, final_msg)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    with patch("pa_agent.ai.anthropic_client._Anthropic", lambda **kw: mock_client):
        client = AnthropicClient(settings)
        client.stream_chat([{"role": "user", "content": "hi"}])

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    assert "thinking" in call_kwargs
    assert call_kwargs["thinking"]["type"] in ("enabled", "adaptive")


def test_stream_chat_no_thinking_config_when_disabled():
    settings = _make_settings(model="anthropic/claude-sonnet-4-5", thinking=False)

    events = [_make_stream_event("message_stop")]
    final_msg = _make_final_message()
    stream_ctx = _make_stream_ctx(events, final_msg)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    with patch("pa_agent.ai.anthropic_client._Anthropic", lambda **kw: mock_client):
        client = AnthropicClient(settings)
        client.stream_chat([{"role": "user", "content": "hi"}])

    call_kwargs = mock_client.messages.stream.call_args.kwargs
    assert "thinking" not in call_kwargs


def test_stream_chat_base_url_passed_when_set():
    settings = _make_settings(base_url="https://my-anthropic-proxy.example.com")

    events = [_make_stream_event("message_stop")]
    final_msg = _make_final_message()
    stream_ctx = _make_stream_ctx(events, final_msg)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    captured: dict = {}

    def fake_anthropic(**kwargs):
        captured.update(kwargs)
        return mock_client

    with patch("pa_agent.ai.anthropic_client._Anthropic", fake_anthropic):
        client = AnthropicClient(settings)
        client.stream_chat([{"role": "user", "content": "hi"}])

    assert captured["base_url"] == "https://my-anthropic-proxy.example.com"


def test_stream_chat_cache_read_tokens_mapped_to_cached():
    settings = _make_settings()
    events = [_make_stream_event("message_stop")]
    final_msg = _make_final_message(cache_read=40)
    stream_ctx = _make_stream_ctx(events, final_msg)

    mock_client = MagicMock()
    mock_client.messages.stream.return_value = stream_ctx

    with patch("pa_agent.ai.anthropic_client._Anthropic", lambda **kw: mock_client):
        client = AnthropicClient(settings)
        reply = client.stream_chat([{"role": "user", "content": "hi"}])

    assert reply.usage.cached_prompt_tokens == 40


# ── client_factory routing ────────────────────────────────────────────────────


def test_client_factory_anthropic_native_by_alias():
    from pa_agent.ai.client_factory import create_ai_client

    settings = _make_settings(model="anthropic/claude-sonnet-4-5", provider_type="auto")
    client = create_ai_client(settings)
    assert isinstance(client, AnthropicClient)


def test_client_factory_anthropic_native_by_explicit_type():
    from pa_agent.ai.client_factory import create_ai_client

    # Even with a non-alias model, explicit provider_type wins.
    settings = _make_settings(model="claude-sonnet-4-5", provider_type="anthropic_native")
    client = create_ai_client(settings)
    assert isinstance(client, AnthropicClient)


def test_client_factory_openai_compat_when_type_forced():
    from pa_agent.ai.client_factory import create_ai_client
    from pa_agent.ai.deepseek_client import DeepSeekClient

    # anthropic alias but provider_type=openai_compat -> DeepSeekClient
    settings = _make_settings(model="anthropic/claude-sonnet-4-5", provider_type="openai_compat")
    client = create_ai_client(settings)
    assert isinstance(client, DeepSeekClient)


def test_update_provider_replaces_settings():
    settings = _make_settings(model="anthropic/claude-sonnet-4-5")
    client = AnthropicClient(settings)
    new_settings = _make_settings(model="anthropic/claude-opus-5")
    client.update_provider(new_settings)
    assert client._settings.model == "anthropic/claude-opus-5"
