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


def test_personalization_reflects_casual_speech_persona_and_emoji() -> None:
    args = {
        **_ARGS,
        "use_formal_speech": False,
        "use_emoji": True,
        "tutor_name": "냥 튜터",
        "tutor_tagline": "친근한 말투 · 비유 잘 씀",
    }

    slide_text = _join(slides_prompts("요청", "outline", 10, "concept_flow", **args))
    voice_text = _join(voice_prompt("요청", "제목", "초점", "요약", 0, **args))

    for text in (slide_text, voice_text):
        assert "말투: 반말체" in text
        assert "친근한 또래 과외쌤 톤" in text
        assert "narration/음성대본에 가벼운 이모지" in text
        assert "튜터 페르소나: 냥 튜터 — 친근한 말투 · 비유 잘 씀" in text


def test_personalization_reflects_formal_speech_and_emoji_ban() -> None:
    args = {**_ARGS, "use_formal_speech": True, "use_emoji": False}

    text = _join(voice_prompt("요청", "제목", "초점", "요약", 0, **args))

    assert "말투: 존댓말" in text
    assert "다정하고 또렷한 과외쌤 톤" in text
    assert "이모지 금지" in text


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


def test_parallel_slide_prompt_requires_structured_visual_spec() -> None:
    system, user = slides_prompts("요청", "outline", 10, "concept_flow", **_ARGS)

    assert "html, css, markdown, mermaid, script, 외부 URL을 절대 생성하지 않는다" in system
    assert "visual은 {type, data} 객체" in system
    assert "number_line, comparison, step_flow, fraction_bar, concept_map, example_box" in system
    assert "중1 수학·수직선·정수 비교·절댓값·분수 단원" in system
    assert "같은 visual.type을 연속 사용하지 말고" in system
    assert "최소 3종 이상" in system
    assert "concept_map은 남발 금지이며 단원당 1~2개" in system
    assert "few-shot" in system
    assert "title(제목)은 해당 슬라이드 내용을 구체적으로 요약한 6~16자 명사구" in system
    assert "챕터명+번호 형태 금지" in system
    assert "음수끼리의 크기 비교" in system
    assert "정형 인트로 반복 금지" in system
    assert "인사말은 첫 슬라이드에서만" in system
    assert "안녕하세요. 오늘 우리가...왜 하필" in system
    assert "narration은 화면 본문으로 바로 읽히는 2~4문장, 200~360자" in system
    assert "narration을 절대 비우거나 생략하면 실패" in system
    assert "category=text인 슬라이드는 visual.type을 metric-card, comparison-table, example_box 중 하나" in system
    assert "text 슬라이드도 metric-card, comparison-table, example_box 중 하나의 visual marker" in user
    assert "few-shot text slide" in system
    assert "오개념 바로잡기" in system


def test_slide_and_voice_system_prompts_ban_cjk_characters() -> None:
    slide_system, _ = slides_prompts("요청", "outline", 10, "concept_flow", **_ARGS)
    voice_system, _ = voice_prompt("요청", "제목", "초점", "요약", 0, **_ARGS)

    assert "한자·중국어 문자 절대 금지" in slide_system
    assert "순수 한글/숫자/영문만 사용" in slide_system
    assert "한자·중국어 문자 절대 금지" in voice_system
    assert "순수 한글/숫자/영문만 사용" in voice_system


def test_single_call_prompt_includes_missing_personalization_fields() -> None:
    request = build_generation_request(_state())

    assert "학습자 수준 Rust 입문자에 맞춰 난이도·용어·예시 조정" in request.user
    assert "학습 목표 빌림 규칙을 코드로 설명" in request.user
    assert "학습자 약점 개념: 소유권, 라이프타임" in request.user
    assert "말투: 반말체" in request.user
    assert "튜터 페르소나: 냥 튜터 — 친근한 말투 · 비유 잘 씀" in request.user


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
        "use_formal_speech": False,
        "use_emoji": True,
        "tutor_name": "냥 튜터",
        "tutor_tagline": "친근한 말투 · 비유 잘 씀",
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
