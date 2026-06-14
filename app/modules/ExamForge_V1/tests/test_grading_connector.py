"""채점/총평 전용 커넥터 선택 회귀 테스트 (2026-06-14 사용자 지시).

모의고사 채점과 피드백(서술형 루브릭 채점 + AI총평)은 Claude Sonnet 을 기본으로 쓰고,
ACTIVE_GRADING_MODEL 한 값으로 교체 가능해야 한다. Claude 즉시 실패 시 gemini 폴백이
붙는지(라이브 채점 하드페일 방지)도 검증한다. 라이브 AI 호출 없이 스텁으로만 검증한다.
"""
from __future__ import annotations

from app.modules.ExamForge_V1.common import ai_bridge
from app.modules.ExamForge_V1.common import config


def test_active_grading_model_defaults_to_claude_sonnet(monkeypatch) -> None:
    """미설정이면 채점 모델은 claude_sonnet 이다."""
    monkeypatch.delenv("ACTIVE_GRADING_MODEL", raising=False)
    assert config.active_grading_model() == "claude_sonnet"


def test_active_grading_model_env_override(monkeypatch) -> None:
    """ACTIVE_GRADING_MODEL 한 값으로 다른 커넥터로 교체된다."""
    monkeypatch.setenv("ACTIVE_GRADING_MODEL", "opus46")
    assert config.active_grading_model() == "opus46"


class _StubConnector:
    def __init__(self, name: str) -> None:
        self.name = name

    def supports(self, _feature: str) -> bool:
        return False


def test_grading_connector_claude_primary_with_gemini_fallback(monkeypatch) -> None:
    """기본 채점 커넥터는 claude_sonnet 을 primary 로, gemini 를 폴백으로 구성한다."""
    monkeypatch.delenv("ACTIVE_GRADING_MODEL", raising=False)
    ai_bridge._GRADING_CONNECTOR_CACHE.clear()

    built: dict[str, _StubConnector] = {}

    def fake_get_connector(name: str):
        return built.setdefault(name, _StubConnector(name))

    monkeypatch.setattr(ai_bridge, "get_connector", fake_get_connector)

    conn = ai_bridge.get_grading_connector()

    # claude_sonnet 이 primary 로 즉시 생성됐다
    assert "claude_sonnet" in built
    # 폴백 래퍼(failover)로 감싸졌고 primary 는 claude 다
    assert conn.supports("fallback") is True
    assert conn._primary.name == "claude_sonnet"  # noqa: SLF001 — 체인 구성 검증


def test_grading_connector_env_override_single_chain(monkeypatch) -> None:
    """ACTIVE_GRADING_MODEL 지정 시 폴백 래핑 없이 그 커넥터를 단일 체인으로 쓴다."""
    monkeypatch.setenv("ACTIVE_GRADING_MODEL", "opus46")
    ai_bridge._GRADING_CONNECTOR_CACHE.clear()
    monkeypatch.setattr(ai_bridge, "get_connector", lambda name: _StubConnector(name))

    conn = ai_bridge.get_grading_connector()
    assert conn.name == "opus46"
    assert conn.supports("fallback") is False
