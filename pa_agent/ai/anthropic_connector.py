"""Anthropic native route (model alias ``anthropic/<model_id>``).

This route uses the Anthropic Messages API directly (requires an Anthropic
API key or a self-hosted Anthropic-compatible endpoint).

Model field conventions
-----------------------

- ``anthropic``: use Anthropic with the default model (``claude-opus-5``).
- ``anthropic/<modelId>``: pin a specific Anthropic model id, e.g.
  ``anthropic/claude-sonnet-4-5``.

When ``provider_type == "anthropic_native"`` the route is forced regardless
of the model alias; ``base_url`` may be empty (official ``api.anthropic.com``)
or point at a self-hosted Anthropic-compatible endpoint.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

_ANTHROPIC_ALIAS = "anthropic"
_ANTHROPIC_DEFAULT_MODEL_ID = "claude-opus-5"


def is_anthropic_native_model(model: str | None) -> bool:
    """True when the user selected the Anthropic native route via alias."""
    m = (model or "").strip().lower()
    if not m:
        return False
    return m == _ANTHROPIC_ALIAS or m.startswith(f"{_ANTHROPIC_ALIAS}/")


def resolve_anthropic_model_id(model: str | None) -> str:
    """Resolve Anthropic model id from the ``anthropic/<id>`` alias.

    ``anthropic/<modelId>`` -> ``<modelId>``
    ``anthropic`` -> ``claude-opus-5``
    """
    raw = (model or "").strip()
    if not is_anthropic_native_model(raw):
        return _ANTHROPIC_DEFAULT_MODEL_ID
    suffix = raw[len(_ANTHROPIC_ALIAS):].lstrip("/")
    return suffix or _ANTHROPIC_DEFAULT_MODEL_ID


def should_use_anthropic_provider(
    model: str | None,
    base_url: str | None = None,
) -> bool:
    """True when settings Save should treat this as Anthropic native route."""
    del base_url
    return is_anthropic_native_model(model)


def is_anthropic_native_route(model: str | None) -> bool:
    """True when API calls should use the Anthropic native route (alias only)."""
    return is_anthropic_native_model(model)


def sync_anthropic_provider_on_load(
    settings: Any,
    *,
    save_path: Any | None = None,
) -> None:
    """No-op for Anthropic native route (no gateway autodetect)."""
    del settings, save_path


def apply_anthropic_provider_to_settings(
    settings: Any,
    *,
    preferred_model: str | None = None,
) -> str | None:
    """Validate *settings.provider* for Anthropic native route.

    Returns None on success, or a user-facing error string.
    """
    model_hint = (preferred_model or getattr(settings.provider, "model", "") or "").strip()
    provider = settings.provider
    # Preserve whatever the user typed as the alias (anthropic or anthropic/<id>)
    provider.model = model_hint or _ANTHROPIC_ALIAS
    # base_url may be empty (official endpoint) or a self-hosted Anthropic endpoint.
    # Leave it as-is; do not force-clear like the Cursor route.

    key = str(getattr(provider, "api_key", "") or "").strip()
    if not key:
        return "Anthropic 路由需要 API Key。请在设置里填写 API Key。"
    return None
