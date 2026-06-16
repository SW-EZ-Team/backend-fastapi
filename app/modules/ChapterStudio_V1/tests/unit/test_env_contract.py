from __future__ import annotations

from pathlib import Path


def test_root_env_example_keeps_secret_slots_blank() -> None:
    env = _backend_env()

    for key in (
        "ANTHROPIC_API_KEY",
        "CLAUDE_SONNET_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
        "TELEGRAM_BOT_TOKEN",
    ):
        assert _value_for(env, key) == ""


def test_root_env_example_declares_chapterstudio_runtime_contract() -> None:
    env = _backend_env()

    assert _value_for(env, "DATABASE_SCHEMA") == "chapter_studio"
    assert _value_for(env, "ACTIVE_PLANNER_MODEL") == "gemini_flash"
    assert _value_for(env, "ACTIVE_TTS_MODEL") == "gemini_tts"
    assert _value_for(env, "EXAMFORGE_VERIFICATION_ADVISORY") == "false"
    assert "TTS_ENDPOINT=" in env


def test_module_env_example_has_local_secret_slots() -> None:
    env = _module_env()

    for key in (
        "ANTHROPIC_API_KEY",
        "CLAUDE_SONNET_API_KEY",
        "GEMINI_API_KEY",
        "FASTAPI_API_KEY",
        "MODAL_TOKEN_ID",
        "MODAL_TOKEN_SECRET",
    ):
        assert _value_for(env, key) == ""


def test_module_env_example_uses_registered_text_connector() -> None:
    env = _module_env()

    assert _value_for(env, "AI_MODEL") == "qwen27b_modal"
    assert _value_for(env, "ACTIVE_TEXT_MODEL") == "qwen27b_sonnet_fallback"
    assert _value_for(env, "EXAMFORGE_VERIFICATION_ADVISORY") == "false"


def _backend_env() -> str:
    return (_backend_root() / ".env.example").read_text(encoding="utf-8")


def _module_env() -> str:
    return (_module_root() / ".env.example").read_text(encoding="utf-8")


def _value_for(env: str, key: str) -> str:
    prefix = f"{key}="
    for line in env.splitlines():
        if line.startswith(prefix):
            return line.removeprefix(prefix)
    raise AssertionError(f"{key} 환경변수 예시가 필요하다.")


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[5]


def _module_root() -> Path:
    return Path(__file__).resolve().parents[2]
