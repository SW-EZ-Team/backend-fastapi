"""ChapterStudio_V1 통합 테스트 — 프로덕션 API 표면을 검증한다."""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
import json
import re

import pytest
from httpx import AsyncClient

from app.modules.ChapterStudio_V1.ai_connectors import registry
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.app.routers import chapter_studio

PERSIST_QUERIES: list[str] = []
PERSIST_ARGS: list[tuple[object, ...]] = []
_PLACEHOLDER = re.compile(r"\$(\d+)")


class FakeTextConnector:
    name = "test_chapterstudio"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return ChapterAIResponse(
            text=json.dumps(_lesson_payload(int(req.extra["slide_count"])), ensure_ascii=False),
            model=self.name,
            input_tokens=12,
            output_tokens=34,
            finish_reason="stop",
        )

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return feature in {"json_mode"}


@pytest.fixture(autouse=True)
def register_fake_connector(monkeypatch: pytest.MonkeyPatch) -> None:
    """외부 AI 호출 없이 실제 ASGI 라우터와 LangGraph 경로만 검증한다."""
    PERSIST_QUERIES.clear()
    PERSIST_ARGS.clear()
    registry.clear_cache()
    monkeypatch.setitem(registry._REGISTRY, "test_chapterstudio", FakeTextConnector)
    monkeypatch.setenv("ACTIVE_TEXT_MODEL", "test_chapterstudio")
    # 이 테스트는 엔드포인트·영속화 배선을 검증한다. self-repair는 전용 단위 테스트에서 다룬다.
    monkeypatch.setenv("CHAPTERSTUDIO_LESSON_SELF_REPAIR", "false")
    monkeypatch.setattr(chapter_studio, "get_connection", fake_get_connection)
    yield
    registry.clear_cache()


@pytest.mark.anyio
async def test_generate_returns_chapter_response(client: AsyncClient) -> None:
    payload = {"lesson_id": "lesson-1"}

    response = await client.post("/api/chapter-studio/generate", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["chapter_id"] == "chapter_lesson-1"
    assert len(data["slides"]) == 10
    assert len(data["quizzes"]) == 10
    assert len(data["voice_scripts"]) == 10
    assert "<iframe" in data["slides"][0]["html_content"]
    assert _has_query("INSERT INTO chapter_studio.slide")
    assert _has_query("INSERT INTO chapter_studio.lesson_generation_status")


@pytest.mark.anyio
async def test_generate_rejects_missing_lesson_id(client: AsyncClient) -> None:
    payload: dict[str, object] = {}

    response = await client.post("/api/chapter-studio/generate", json=payload)

    assert response.status_code == 422


class FakeConnection:
    async def fetchrow(self, query: str, *args: object) -> dict[str, object] | None:
        assert "WHERE cu.lesson_id = $1" in query
        assert args == ("lesson-1",)
        return {
            "lesson_id": "lesson-1",
            "tutoring_id": "tutoring-1",
            "user_id": "spring-user-1",
            "curriculum_plan_id": "curriculum-1",
            "topic": "파이썬 리스트 컴프리헨션",
            "source_mode": "topic",
            "pdf_file_name": "",
            "chapter_title": "리스트 컴프리헨션",
            "chapter_brief": "파이썬 리스트 컴프리헨션",
            "learning_goal": "반복과 조건을 한 줄 표현으로 이해한다.",
            "slide_count": 10,
            "template": "concept_code",
            "generation_context": {
                "duration_days": 30,
                "depth": "normal",
                "teacher": "owl",
                "tone": 50,
                "pace": 50,
                "tutor_depth": 60,
                "socratic": 70,
                "audience_level": "프로그래밍 입문자",
                "weak_points": "for 루프와 조건식 조합",
            },
        }

    def transaction(self) -> FakeTransaction:
        return FakeTransaction()

    async def execute(self, query: str, *args: object) -> object:
        expected = max((int(match) for match in _PLACEHOLDER.findall(query)), default=0)
        assert len(args) == expected, query
        PERSIST_QUERIES.append(query)
        PERSIST_ARGS.append(args)
        return "OK"


class FakeTransaction:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


@asynccontextmanager
async def fake_get_connection() -> AsyncIterator[FakeConnection]:
    yield FakeConnection()


def _has_query(needle: str) -> bool:
    return any(needle in query for query in PERSIST_QUERIES)


def _lesson_payload(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_slide(idx) for idx in range(slide_count)],
        "quizzes": [_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [
            {
                "heading": "핵심",
                "bullets": [
                    "리스트 컴프리헨션은 반복과 조건을 한 줄로 표현해 코드를 간결하게 만듭니다.",
                    "출력식, 반복 변수, 조건의 순서를 정확히 구분하는 것이 가장 중요합니다.",
                ],
            },
            {
                "heading": "주의",
                "bullets": [
                    "복잡한 조건이 여러 개 겹치면 오히려 일반 for 문이 더 읽기 쉽습니다.",
                    "한 줄에 억지로 몰아넣으면 가독성이 떨어지므로 적절히 풀어 쓰는 판단이 필요합니다.",
                ],
            },
            {
                "heading": "복습",
                "bullets": [
                    "입력, 반복 변수, 조건, 출력식을 순서대로 짚으며 동작을 머릿속으로 따라갑니다.",
                    "작은 예시를 손으로 돌려 보면서 결과 리스트가 어떻게 만들어지는지 확인합니다.",
                ],
            },
        ],
        "assignment": {
            "title": "리스트 컴프리헨션 변환 과제",
            "assignment_format": "코드 변환과 설명",
            "expected_minutes": 20,
            "steps": ["for 문을 컴프리헨션으로 바꿉니다.", "조건식을 추가합니다.", "읽기 쉬운지 설명합니다."],
            "rubric": ["동작이 같다.", "조건식이 정확하다.", "설명이 충분하다."],
        },
        "voice_scripts": [
            {
                "slide_idx": idx,
                "script_text": f"{idx + 1}번 슬라이드에서는 리스트 컴프리헨션의 핵심 흐름을 과외식으로 차근차근 설명합니다.",
            }
            for idx in range(slide_count)
        ],
    }


def _slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"{idx + 1}단계",
        "focus": "반복 흐름 이해",
        "checkpoint": "출력식과 조건식을 구분할 수 있다.",
        "category": "text",
        "html": f"<section><h2>{idx + 1}단계</h2><p>리스트 컴프리헨션의 흐름을 문장으로 확인합니다.</p></section>",
        "css": ".slide{font-family:sans-serif;}",
    }


def _quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": "리스트 컴프리헨션에서 가장 먼저 확인할 요소는 무엇인가요?",
        "choices": ["출력식", "파일명", "패키지 버전", "운영체제"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "출력식이 새 리스트의 각 원소를 결정하므로 가장 먼저 확인해야 합니다. 조건식부터 보면 흐름을 놓치기 쉽습니다.",
    }
