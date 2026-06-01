from __future__ import annotations

import json

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.pipeline.payload import parse_payload
from app.modules.ChapterStudio_V1.pipeline.quality import check_payload
from app.modules.ChapterStudio_V1.pipeline.repair import repair_payload

_LONG_VOICE = (
    "자, 이번 화면에서는 핵심 개념을 왜 이렇게 봐야 하는지 직관부터 아주 차근차근 풀어서 설명해 보겠습니다. "
    "먼저 이 개념이 실제로 어디에서 쓰이는지, 구체적인 예시 두세 가지를 머릿속에 떠올리며 감을 잡아 봅시다. "
    "그다음 작동 방식을 한 단계씩 따라가면서, 어떤 값이 들어와서 어떤 값으로 바뀌어 나가는지 천천히 살펴보겠습니다. "
    "여기서 많은 학습자가 헷갈리는 지점은 바로 경계 조건을 정확히 나누는 부분인데요, 한 번 멈춰서 직접 손으로 그려 보면 훨씬 또렷해집니다. "
    "실전에서는 입력이 아예 비어 있거나 원소가 딱 한 개만 남는 경우를 따로 점검하는 습관이 정말 중요합니다. "
    "자주 빠지는 오답 함정은 종료 조건을 잘못 잡아서 마지막 한 칸을 통째로 놓치는 경우인데요, 이 부분을 꼭 기억해 두세요. "
    "이 약점은 작은 예시 두세 개를 직접 손으로 끝까지 돌려 보면 의외로 금방 교정됩니다. "
    "그러니 지금 20초만 투자해서, 가장 작은 입력 하나를 골라 결과를 미리 예측해 보시기 바랍니다. "
    "조금 더 욕심을 내자면, 원소가 두 개이거나 세 개인 경우도 같은 방식으로 손으로 따라가 보면 자신감이 한층 붙습니다. "
    "이렇게 작은 사례부터 차곡차곡 쌓아 두면, 시험장에서 비슷한 문제를 만났을 때 당황하지 않고 빠르게 판단할 수 있습니다. "
    "특히 처음에는 느리더라도 정확하게 따라가는 연습이, 결국 빠르고 정확한 풀이로 이어진다는 점을 꼭 기억해 두시기 바랍니다. "
    "마지막으로 다음 화면에서는 지금 설명한 내용을 실제 코드로 한 줄씩 직접 확인해 보면서 차분하게 마무리하겠습니다."
)
_LONG_EXPLANATION = (
    "정답은 A이며, 나머지 보기는 핵심 개념을 잘못 적용한 흔한 오답 함정입니다. "
    "특히 경계 조건을 놓쳐서 마지막 한 칸을 검사하지 못하는 약점과 직접 연결되므로, 종료 조건을 끝까지 따져 보는 습관이 필요합니다."
)


class _RepairConnector:
    """미달 항목을 채워 주는 정상 repair 커넥터(테스트용)."""

    name = "repair_fake"

    def __init__(self, slide_count: int) -> None:
        self._slide_count = slide_count

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        body = {
            "voice_scripts": [{"slide_idx": idx, "script_text": _LONG_VOICE} for idx in range(self._slide_count)],
            "quiz_explanations": [{"slide_idx": idx, "explanation": _LONG_EXPLANATION} for idx in range(self._slide_count)],
        }
        return _resp(json.dumps(body, ensure_ascii=False))

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


class _BrokenConnector:
    """repair 응답이 깨진 경우(graceful 폴백 검증용)."""

    name = "broken_fake"

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        return _resp("이건 JSON이 아니라 그냥 사과문입니다.")

    async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
        return [await self.generate(req) for req in reqs]

    def supports(self, feature: str) -> bool:
        return True


def _resp(text: str) -> ChapterAIResponse:
    return ChapterAIResponse(text=text, model="fake", input_tokens=1, output_tokens=1, finish_reason="stop")


def test_check_payload_flags_shallow_voice_and_explanation() -> None:
    payload = parse_payload(json.dumps(_shallow_payload(10), ensure_ascii=False), 10)

    report = check_payload(payload)

    assert not report.is_ok()
    assert report.voice_targets() == set(range(10))
    assert report.supporting_needs_repair()


def test_check_payload_passes_rich_payload() -> None:
    payload = parse_payload(json.dumps(_rich_payload(10), ensure_ascii=False), 10)

    assert check_payload(payload).is_ok()


@pytest.mark.anyio
async def test_repair_fills_shallow_materials_and_keeps_indices() -> None:
    payload = parse_payload(json.dumps(_shallow_payload(10), ensure_ascii=False), 10)
    report = check_payload(payload)

    repaired = await repair_payload(_RepairConnector(10), payload, report, 10)

    assert {script.slide_idx for script in repaired.voice_scripts} == set(range(10))
    assert {quiz.slide_idx for quiz in repaired.quizzes} == set(range(10))
    assert all(len(script.script_text) >= 700 for script in repaired.voice_scripts)
    assert all("오답 함정" in quiz.explanation for quiz in repaired.quizzes)
    # 보강 후에는 self-check가 통과해야 한다.
    assert check_payload(repaired).is_ok()


@pytest.mark.anyio
async def test_repair_is_graceful_on_broken_response() -> None:
    payload = parse_payload(json.dumps(_shallow_payload(10), ensure_ascii=False), 10)
    report = check_payload(payload)

    repaired = await repair_payload(_BrokenConnector(), payload, report, 10)

    # 깨진 응답이면 원본을 그대로 유지한다(예외로 죽지 않는다).
    assert repaired.voice_scripts[0].script_text == payload.voice_scripts[0].script_text


@pytest.mark.anyio
async def test_repair_skips_when_no_deficiency() -> None:
    payload = parse_payload(json.dumps(_rich_payload(10), ensure_ascii=False), 10)
    report = check_payload(payload)

    # 미달이 없으면 커넥터를 호출하지 않고 원본을 그대로 반환한다.
    class _NoCall:
        name = "nocall"

        async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
            raise AssertionError("미달이 없으면 repair 호출이 없어야 한다.")

        async def generate_batch(self, reqs: list[ChapterAIRequest]) -> list[ChapterAIResponse]:
            raise AssertionError("호출되면 안 된다.")

        def supports(self, feature: str) -> bool:
            return True

    repaired = await repair_payload(_NoCall(), payload, report, 10)
    assert repaired is payload


def _shallow_payload(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_rich_slide(idx) for idx in range(slide_count)],
        "quizzes": [_shallow_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [_rich_note(idx) for idx in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [
            {
                "slide_idx": idx,
                "script_text": "이번 슬라이드의 핵심을 짧게 한 문장으로만 설명하고 끝내는, 분량이 부족한 얕은 음성 대본입니다.",
            }
            for idx in range(slide_count)
        ],
    }


def _rich_payload(slide_count: int) -> dict[str, object]:
    return {
        "slides": [_rich_slide(idx) for idx in range(slide_count)],
        "quizzes": [_rich_quiz(idx) for idx in range(slide_count)],
        "note_blocks": [_rich_note(idx) for idx in range(4)],
        "assignment": _assignment(),
        "voice_scripts": [{"slide_idx": idx, "script_text": _LONG_VOICE} for idx in range(slide_count)],
    }


def _rich_slide(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "title": f"슬라이드 {idx}",
        "focus": "핵심 흐름",
        "checkpoint": "자가점검",
        "category": "text",
        "html": (
            "<section><h2>핵심 개념을 한 화면에서 차근차근 정리해 보겠습니다.</h2>"
            "<p>먼저 이 개념이 왜 중요한지, 어디에서 쓰이는지 배경부터 천천히 설명합니다.</p>"
            "<p>다음으로 실제 동작 방식을 작은 예시와 함께 한 단계씩 살펴봅니다.</p>"
            "<p>마지막으로 자주 틀리는 지점과 직접 점검하는 방법을 함께 짚어 봅니다.</p></section>"
        ),
        "css": "",
    }


def _shallow_quiz(idx: int) -> dict[str, object]:
    return {
        "slide_idx": idx,
        "question": "질문입니다.",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "이해",
        "explanation": "정답은 A이며 나머지 세 보기는 모두 틀린 보기입니다.",
    }


def _rich_quiz(idx: int) -> dict[str, object]:
    return {**_shallow_quiz(idx), "explanation": _LONG_EXPLANATION}


def _rich_note(idx: int) -> dict[str, object]:
    return {
        "heading": f"핵심 {idx}",
        "bullets": [
            "핵심 개념을 한 문장으로 다시 정리하면서, 이 개념이 왜 중요한지 배경까지 함께 복습합니다.",
            "실수하기 쉬운 경계 조건을 작은 예시로 직접 손으로 점검하는 습관을 평소에 만들어 둡니다.",
            "오해하기 쉬운 부분을 반례와 함께 다시 한 번 짚어 가며, 정확한 판단 기준을 세워 둡니다.",
        ],
    }


def _assignment() -> dict[str, object]:
    return {
        "title": "실습 과제",
        "assignment_format": "문제풀이+근거 표시",
        "expected_minutes": 30,
        "steps": ["핵심 개념을 직접 적용해 봅니다.", "결과를 근거와 함께 정리합니다."],
        "rubric": ["근거가 명확한가", "예외 처리가 정확한가"],
    }
