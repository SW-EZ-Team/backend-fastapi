"""컴포넌트 병렬 생성 프롬프트 문자열.

parallel_prompts.py에서 프롬프트 텍스트 구성 책임만 떼어낸 모듈이다. 각 컴포넌트
(slides/quizzes/note/assignment/voice)별로 (system, user) 쌍을 만든다. 분량·구조 계약은
기존 단일콜 prompt.py와 동일한 수치 기준을 따르되, 해당 컴포넌트에만 한정한다. 어떤 LLM도
호출하지 않는 순수 함수만 둔다.
"""
from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.personalization import personalization_contract

_JSON_RULE = "출력은 단일 JSON 객체 한 개뿐이며 markdown fence·설명문·사고과정·<think> 블록을 금지한다. "


def slides_prompts(brief: str, outline: str, slide_count: int, template_key: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str) -> tuple[str, str]:
    """슬라이드 배열만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, "슬라이드는 개인화 계약에 맞춰 예시·용어·오개념 교정 단서를 화면에 짧게 배치한다.")
    system = (
        "너는 ChapterStudio_V1의 슬라이드 생성기다. "
        + _JSON_RULE
        + "최상위 키는 slides 하나만 쓴다. "
        f"slides는 정확히 {slide_count}개이고 slide_idx는 0..{slide_count - 1} 완전집합이다. "
        "slides[i] 키는 정확히 slide_idx, title, focus, checkpoint, category, html, css 일곱 개다. "
        "category는 text, diagram, code, math, chart, interactive, table 중 하나만 쓰고 시각요소 이름을 값으로 쓰면 실패다. "
        "category별 필수 시각요소: diagram은 <pre class=\"mermaid\">, code는 <pre><code data-lang>, "
        "math는 <div class=\"formula\">, chart는 chart-box data-chart-spec, table은 <table>, "
        "interactive는 <details>를 반드시 1회 이상 넣는다. "
        "mermaid 노드 라벨에 대괄호 [] 금지(중첩 대괄호 금지). "
        "스택·배열 상태는 괄호()나 쉼표로 표현한다. "
        "콜론·괄호 등 특수문자 라벨은 A[\"초기 상태: 빈 스택\"]처럼 큰따옴표로 감싼다. "
        "edge 라벨에 화살표 기호(->) 등 mermaid 예약기호를 넣지 않는다. 한 라벨은 한 줄로 끝낸다. "
        "각 slide.html은 마침표로 끝나는 완전한 한국어 문장 4~7개(200~360자)를 담고 핵심어 나열로 끝내지 않는다. "
        "모든 html은 section 내부 조각이며 script 태그·외부 URL을 쓰지 않는다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"선택 템플릿: {template_key}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        f"위 역할에 맞춰 슬라이드 {slide_count}개를 1:1 과외 말투로 만든다. "
        "긴 설명은 화면에 넣지 말고 짧은 핵심 설명과 시각자료만 둔다."
    )
    return system, user


def quizzes_prompts(brief: str, outline: str, slide_count: int, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str) -> tuple[str, str]:
    """퀴즈 배열만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="퀴즈는 약점 개념을 직접 겨냥한 진단·교정형 문항을 우선한다.")
    system = (
        "너는 ChapterStudio_V1의 퀴즈 생성기다. "
        + _JSON_RULE
        + "최상위 키는 quizzes 하나만 쓴다. "
        f"quizzes는 정확히 {slide_count}개이고 slide_idx는 0..{slide_count - 1} 완전집합이다. "
        "quizzes[i] 키는 정확히 slide_idx, question, choices, answer_idx, difficulty, explanation 여섯 개다. "
        "choices는 문자열 4개 배열, answer_idx는 0~3 정수이며 정답은 한 보기에만 해당한다. "
        "difficulty는 기억, 이해, 적용, 함정 교정, 실전 판단, 오해 중 하나만 쓴다. Easy/Medium/Hard 금지. "
        "explanation은 120~180자로 정답 이유와 오답 함정을 함께 적고 약점 개념과 연결한다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        f"각 slide_idx마다 그 슬라이드 내용에서만 출제한 퀴즈 1개씩, 총 {slide_count}개를 만든다."
    )
    return system, user


def note_prompts(brief: str, outline: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str) -> tuple[str, str]:
    """핵심 노트(note_blocks)만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, "노트는 개인화 계약에 맞춰 복습 우선순위와 bullet 예시를 조정한다.")
    system = (
        "너는 ChapterStudio_V1의 핵심 노트 생성기다. "
        + _JSON_RULE
        + "최상위 키는 note_blocks 하나만 쓴다. "
        "note_blocks는 정확히 4개이고 각 block은 heading과 정확히 3개 bullets를 가진다. "
        "note_blocks[i] 키는 정확히 heading, bullets 두 개이며 title 키를 쓰지 않는다. "
        "각 bullet은 45자 이상의 완결 문장이다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        "강의 전체를 복습할 수 있는 핵심 노트 4블록을 만든다."
    )
    return system, user


def assignment_prompts(brief: str, outline: str, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str) -> tuple[str, str]:
    """과제(assignment)만 생성하는 (system, user) 프롬프트를 만든다."""
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="과제는 약점 개념을 훈련하는 과제로 구성한다.")
    system = (
        "너는 ChapterStudio_V1의 과제 생성기다. "
        + _JSON_RULE
        + "최상위 키는 assignment 하나만 쓴다. "
        "assignment는 title, assignment_format, expected_minutes(20~40 정수), steps, rubric을 모두 채운다. "
        "steps와 rubric은 반드시 문자열 배열(list)이며 dict나 객체로 쓰면 실패다. "
        "steps는 3~5개, rubric은 3~5개의 완결 문장이다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"확정 슬라이드 역할:\n{outline}\n"
        f"{personalization}\n"
        "강의 내용을 직접 적용해 볼 실습 과제 1개를 만든다."
    )
    return system, user


def voice_prompt(
    brief: str, slide_title: str, slide_focus: str, slide_summary: str, slide_idx: int, *, weak_points: str, audience_level: str, tone: int, pace: int, tutor_depth: int, socratic: int, learning_goal: str
) -> tuple[str, str]:
    """슬라이드 1개의 음성대본만 생성하는 (system, user) 프롬프트를 만든다.

    xgrammar가 minLength를 완전히 강제하지 못하는 실측을 보완하기 위해 프롬프트에 구체적
    분량(900~1600자)과 4단 구조를 명시해 모델이 충분한 길이를 스스로 지키게 한다.
    """
    personalization = _personalization(weak_points, audience_level, tone, pace, tutor_depth, socratic, learning_goal, weak_rule="음성대본은 약점 개념을 더 천천히·예시 많이 설명하고 오개념을 짚는다.")
    system = (
        "너는 ChapterStudio_V1의 음성대본 생성기다. "
        + _JSON_RULE
        + "키는 정확히 slide_idx, script_text 두 개다. "
        # 분량 하한을 숫자로 못 박고 4단 구조를 강제 — xgrammar minLength 미강제 보완.
        "script_text는 반드시 900~1600자 범위여야 한다(900자 미만이면 실패로 간주한다). "
        "분량 기준: ① 도입(이 개념이 왜 중요한지 배경 2~3문장) ② 핵심 설명(개념·원리 3~4문장) "
        "③ 구체적 예시·직관(한 번에 이해되는 사례 2~3문장) ④ 마무리 복습(다음 화면 연결·자가점검 1~2문장). "
        "총 8~12문장, 과외 선생님 자연스러운 존댓말 한 문단으로 완성한다. "
        "화면에 없는 깊은 설명·실수하기 쉬운 지점·바로 해볼 미니연습을 포함한다. "
        "900자 미만의 짧은 대본(한두 문장 나열)은 절대 허용되지 않는다. "
        "HTML 태그·markdown·괄호 지시문을 넣지 않는다.\n"
        f"{personalization}"
    )
    user = (
        f"강의 요청: {brief}\n"
        f"대상 슬라이드: slide_idx={slide_idx} / 제목={slide_title} / 초점={slide_focus}\n"
        f"화면 요약: {slide_summary}\n"
        f"{personalization}\n"
        "위 슬라이드의 음성대본을 900~1600자 범위로 만든다. "
        "도입→핵심설명→구체예시→마무리복습 순서를 지킨다. "
        f"slide_idx는 반드시 {slide_idx}로 고정한다."
    )
    return system, user


def _personalization(
    weak_points: str,
    audience_level: str,
    tone: int,
    pace: int,
    tutor_depth: int,
    socratic: int,
    learning_goal: str,
    component_rule: str = "",
    *,
    weak_rule: str = "",
) -> str:
    return personalization_contract(
        weak_points=weak_points,
        audience_level=audience_level,
        tone=tone,
        pace=pace,
        tutor_depth=tutor_depth,
        socratic=socratic,
        learning_goal=learning_goal,
        component_rule=component_rule,
        weak_component_rule=weak_rule,
    )


def clean_raw_voice_text(text: str) -> str:
    """raw 텍스트 폴백용 — think·fence 제거 후 앞뒤 따옴표·마크다운 잔재를 걷어낸다.

    Qwen이 JSON 대신 대본 자체를 반환할 때 script_text로 쓸 수 있는 깨끗한 텍스트를 만든다.
    clean_llm_text가 think 블록·코드펜스를 제거하고, 이후 앞뒤 큰따옴표만 추가 제거한다.
    """
    from common.llm_output import clean_llm_text  # 지역 import — 순환 방지
    cleaned = clean_llm_text(text).strip()
    # JSON 문자열 리터럴처럼 앞뒤가 따옴표로 감싸인 경우 벗겨낸다.
    if cleaned.startswith('"') and cleaned.endswith('"') and len(cleaned) >= 2:
        cleaned = cleaned[1:-1]
    return cleaned


__all__ = [
    "assignment_prompts",
    "clean_raw_voice_text",
    "note_prompts",
    "quizzes_prompts",
    "slides_prompts",
    "voice_prompt",
]
