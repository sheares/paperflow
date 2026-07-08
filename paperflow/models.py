"""Fireworks model registry — short aliases for the reconciler + router.

Reconciler and router both read the FIREWORKS_MODEL env var. Users can
set the full slug ("accounts/fireworks/models/deepseek-v4-pro") or a
short alias from this registry ("deepseek", "minimax", "qwen", "glm").

Only DeepSeek V4 Pro's slug is confirmed on our Fireworks account; the
others are conventional guesses at Fireworks' naming pattern. If a
slug does not resolve, Fireworks returns 404 and the router / reconciler
degrade to local rules (visible in the router log as `remote_failed`).
Prices are per-million tokens, listed as (input, output) in USD, and
are used by eval/model_ab.py to estimate per-call cost.
"""
from __future__ import annotations

MODEL_PROFILES: dict[str, dict] = {
    "deepseek": {
        "slug": "accounts/fireworks/models/deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "price_in":  1.74,
        "price_out": 3.48,
        "context":  1_000_000,
    },
    "minimax": {
        "slug": "accounts/fireworks/models/minimax-m3",
        "label": "Minimax M3",
        "price_in":  0.30,
        "price_out": 1.20,
        "context":    512_000,
    },
    "qwen": {
        "slug": "accounts/fireworks/models/qwen3p7-plus",
        "label": "Qwen 3.7 Plus",
        "price_in":  0.40,
        "price_out": 1.60,
        "context":    128_000,
    },
    "glm": {
        "slug": "accounts/fireworks/models/glm-5p2",
        "label": "GLM 5.2",
        "price_in":  1.40,
        "price_out": 4.40,
        "context":  1_000_000,
    },
}


def resolve(value: str) -> str:
    """Return the full Fireworks model slug for either an alias
    ('minimax') or a bare slug ('accounts/fireworks/models/x'). Missing
    aliases return the input string unchanged so a full custom slug
    still works."""
    p = MODEL_PROFILES.get(value.lower())
    return p["slug"] if p else value


def profile(value: str) -> dict | None:
    """Return the registry entry for either an alias or the exact slug it
    resolves to, else None."""
    key = value.lower()
    if key in MODEL_PROFILES:
        return MODEL_PROFILES[key]
    for p in MODEL_PROFILES.values():
        if p["slug"] == value:
            return p
    return None
