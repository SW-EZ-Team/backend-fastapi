"""parse_source_node 회귀 테스트 (2026-06-14 시연 드라이런 발견).

gemini 등 LLM이 {"topics":[...]} 객체 대신 topics 배열을 최상위로 반환하면
data.get(...) 가 'list' object has no attribute 'get' 로 깨져 폴백(1개념)으로 떨어졌고,
그 결과 source_capacity 가 1세그먼트로 뭉개져 20문항 모의고사가 5문항으로 캡됐다.
parse_source_node 가 list/dict 양쪽 응답을 모두 처리하는지 검증한다.

라이브 AI 호출 없이 가짜 커넥터로만 검증한다.
"""
from __future__ import annotations

import json

import pytest

from app.modules.ExamForge_V1.common.source_capacity import (
    count_distinct_concepts,
    count_source_segments,
)
from app.modules.ExamForge_V1.pipeline.nodes import parse_source_node as psn


class _FakeResp:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeConnector:
    """주제추출 AI 응답을 고정 텍스트로 돌려주는 스텁."""

    def __init__(self, text: str) -> None:
        self._text = text

    async def generate(self, _req):  # noqa: ANN001
        return _FakeResp(self._text)

    def supports(self, _f: str) -> bool:
        return True


_TOPICS = [
    {"name": "프로세스와 스레드", "sub_concepts": ["PCB", "문맥 교환"], "keywords": ["스택", "힙"]},
    {"name": "CPU 스케줄링", "sub_concepts": ["FCFS", "SJF"], "keywords": ["선점", "비선점"]},
    {"name": "동기화", "sub_concepts": ["뮤텍스", "세마포어"], "keywords": ["임계구역"]},
]


@pytest.mark.asyncio
async def test_parse_handles_toplevel_list_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """LLM이 최상위 배열을 반환해도 폴백 없이 topics 를 추출한다."""
    monkeypatch.setattr(psn, "get_planner_connector", lambda: _FakeConnector(json.dumps(_TOPICS)))
    state = {"source_text": "운영체제 학습 자료 " * 200, "subject": "운영체제"}
    result = await psn.parse_source_node(state)
    topics = result["topics"]
    # 폴백(1개념)이 아니라 실제 다중 토픽이 추출돼야 한다
    assert len(topics) >= 3
    assert count_distinct_concepts(topics) >= 3
    assert count_source_segments(topics) >= 2
    assert "폴백" not in (result.get("error_message") or "")


@pytest.mark.asyncio
async def test_parse_handles_object_response(monkeypatch: pytest.MonkeyPatch) -> None:
    """기존 {"topics":[...]} 객체 응답도 그대로 동작한다(회귀 방지)."""
    payload = json.dumps({"topics": _TOPICS, "concept_graph": {"edges": []}})
    monkeypatch.setattr(psn, "get_planner_connector", lambda: _FakeConnector(payload))
    state = {"source_text": "운영체제 학습 자료 " * 200, "subject": "운영체제"}
    result = await psn.parse_source_node(state)
    assert len(result["topics"]) >= 3
    assert count_source_segments(result["topics"]) >= 2
