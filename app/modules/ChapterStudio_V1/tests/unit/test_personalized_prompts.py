from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.parallel_prompt_text import (
    assignment_prompts,
    note_prompts,
    quizzes_prompts,
    slides_prompts,
    voice_prompt,
)
from app.modules.ChapterStudio_V1.pipeline.prompt import build_generation_request
from app.modules.ChapterStudio_V1.pipeline.state import ChapterStudioState

_ARGS = {
    "weak_points": "소유권, 라이프타임",
    "audience_level": "Rust 입문자",
    "tone": 70,
    "pace": 20,
    "tutor_depth": 80,
    "socratic": 90,
    "learning_goal": "빌림 규칙을 코드로 설명",
}


def test_parallel_component_prompts_include_personalization() -> None:
    texts = [
        _join(slides_prompts("요청", "outline", 10, "concept_flow", **_ARGS)),
        _join(quizzes_prompts("요청", "outline", 10, **_ARGS)),
        _join(note_prompts("요청", "outline", **_ARGS)),
        _join(assignment_prompts("요청", "outline", **_ARGS)),
        _join(voice_prompt("요청", "제목", "초점", "요약", 0, **_ARGS)),
    ]

    for text in texts:
        assert "학습자 수준 Rust 입문자에 맞춰 난이도·용어·예시 조정" in text
        assert "학습 목표 빌림 규칙을 코드로 설명" in text
        assert "학습자 약점 개념: 소유권, 라이프타임" in text
        assert "말투는" in text
        assert "질문 스타일은" in text


def test_weak_points_empty_is_noop_for_weak_specific_rules() -> None:
    args = {**_ARGS, "weak_points": ""}

    text = _join(assignment_prompts("요청", "outline", **args))

    assert "학습자 약점 개념" not in text
    assert "약점 개념을 훈련" not in text


def test_required_weak_rules_are_component_specific() -> None:
    quiz_text = _join(quizzes_prompts("요청", "outline", 10, **_ARGS))
    assignment_text = _join(assignment_prompts("요청", "outline", **_ARGS))
    voice_text = _join(voice_prompt("요청", "제목", "초점", "요약", 1, **_ARGS))

    assert "진단·교정형 문항" in quiz_text
    assert "약점 개념을 훈련하는 과제" in assignment_text
    assert "더 천천히·예시 많이 설명" in voice_text


def test_parallel_slide_prompt_includes_mermaid_safe_edge_rule() -> None:
    system, _ = slides_prompts("요청", "outline", 10, "concept_flow", **_ARGS)

    assert "mermaid 노드 라벨에 대괄호 [] 금지" in system
    assert "edge 라벨에 화살표 기호(->) 등 mermaid 예약기호를 넣지 않는다" in system
    assert "한 라벨은 한 줄" in system


def test_single_call_prompt_includes_missing_personalization_fields() -> None:
    request = build_generation_request(_state())

    assert "학습자 수준 Rust 입문자에 맞춰 난이도·용어·예시 조정" in request.user
    assert "학습 목표 빌림 규칙을 코드로 설명" in request.user
    assert "학습자 약점 개념: 소유권, 라이프타임" in request.user


def _join(pair: tuple[str, str]) -> str:
    return "\n".join(pair)


def _state() -> ChapterStudioState:
    return {
        "slide_count": 10,
        "template_key": "concept_flow",
        "topic": "Rust 소유권",
        "source_mode": "topic",
        "pdf_file_name": "",
        "duration_days": 14,
        "depth": "normal",
        "teacher": "owl",
        "tone": 70,
        "pace": 20,
        "tutor_depth": 80,
        "socratic": 90,
        "audience_level": "Rust 입문자",
        "learning_goal": "빌림 규칙을 코드로 설명",
        "weak_points": "소유권, 라이프타임",
        "enriched_brief": "Rust 소유권 강의",
        "reference_context_prompt": "",
        "slide_outline": [
            {"slide_idx": idx, "category": "text", "role": f"역할 {idx}", "must_have": []}
            for idx in range(10)
        ],
    }
