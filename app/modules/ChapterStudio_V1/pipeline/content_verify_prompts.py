"""내용 정확성 검증/교정 프롬프트 빌더.

검증 패스(사실·논리 오류 탐지)와 교정 패스(지목된 오류만 정확히 재작성)의 system/user
프롬프트를 만든다. codex(gpt-5.5)·Qwen3.6·Claude 어느 모델이든 같은 구조로 동작하도록
지시를 명시적·구조화하고, 검증 프롬프트에는 few-shot 1개(오류 있는 예시→검출 결과)를 둔다.
어떤 LLM도 직접 호출하지 않는 순수 함수만 둔다.

공개 API:
    - verify_system() / verify_user(payload)            : 검증 패스 프롬프트
    - correct_system() / correct_user(payload, errors)  : 교정 패스 프롬프트
"""
from __future__ import annotations

import re
from html import unescape

from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload

# 슬라이드 본문은 요약만 보내 토큰을 아끼되, 예시·정의의 사실성을 판단할 만큼은 남긴다.
_SLIDE_SUMMARY_CHARS = 600


def verify_system() -> str:
    """검증기 역할·출력 계약을 고정한다. 출력은 단일 JSON 객체 하나뿐이다."""
    return (
        "너는 엄격한 교과 내용 검수자다. 아래 강의 산출물에서 사실 오류, 논리적 모순, "
        "틀린 예시, 정의 오류만 찾는다. 특히 예시가 실제로 주장을 입증하는지(반례·경계 "
        "예시의 정확성), 정의가 정확한지 검사한다. 문체·분량·맞춤법·취향은 평가 대상이 "
        "아니며, 명백히 틀린 내용만 지적한다. 애매하거나 확신이 낮으면 지적하지 않는다. "
        "출력은 단일 JSON 객체 하나뿐이며 JSON 외 텍스트, 사고과정, markdown fence, "
        "<think> 블록을 금지한다. 최상위 키는 errors 하나만 쓴다. errors는 배열이고 각 "
        "항목은 정확히 location, field, slide_idx, what_is_wrong, correction 다섯 키를 "
        "가진다. field는 slide, quiz, voice 중 하나, slide_idx는 해당 인덱스 정수, "
        "what_is_wrong은 무엇이 왜 틀렸는지, correction은 올바른 내용이다. 오류가 없으면 "
        "errors를 빈 배열로 둔다.\n"
        + _verify_fewshot()
    )


def _verify_fewshot() -> str:
    """오류 있는 예시 → 검출 결과 few-shot 1개. 모델 종류와 무관하게 형식을 고정한다."""
    return (
        "예시 입력(오류 포함): slide 2 본문에 \"스택(stack)은 FIFO 구조로, 먼저 넣은 "
        "값이 먼저 나온다\"라고 적혀 있다.\n"
        "예시 출력(검출 결과): "
        '{"errors":[{"location":"slide 2 본문","field":"slide","slide_idx":2,'
        '"what_is_wrong":"스택은 LIFO(후입선출)인데 FIFO로 잘못 정의했다. 먼저 넣은 값이 '
        '먼저 나오는 것은 큐(queue)다.","correction":"스택은 LIFO 구조로, 나중에 넣은 값이 '
        '먼저 나온다."}]}'
    )


def verify_user(payload: GeneratedLessonPayload) -> str:
    """검증 대상 산출물(슬라이드 본문 요약·퀴즈·voice)을 인덱스와 함께 펼친다."""
    lines = ["아래 강의 산출물을 검수하고 오류만 JSON으로 보고한다.\n"]
    lines.append("[슬라이드 본문]")
    for slide in payload.slides:
        lines.append(f"- slide {slide.slide_idx} (제목={slide.title}): {_plain(slide.html)}")
    lines.append("\n[퀴즈]")
    for quiz in payload.quizzes:
        answer = quiz.choices[quiz.answer_idx] if 0 <= quiz.answer_idx < len(quiz.choices) else "?"
        lines.append(
            f"- quiz {quiz.slide_idx}: 질문={quiz.question} / 정답={answer} / 해설={quiz.explanation}"
        )
    lines.append("\n[음성대본의 예시·주장]")
    for script in payload.voice_scripts:
        lines.append(f"- voice {script.slide_idx}: {script.script_text}")
    lines.append("\n오류가 없으면 errors를 빈 배열로 둔다. 명백한 오류만 지적한다.")
    return "\n".join(lines)


def verify_user_group(payload: GeneratedLessonPayload, group: str) -> str:
    """검증 대상을 한 그룹(slides/quizzes/voice)으로 한정해 펼친다(병렬 검증용).

    그룹별로 검증 콜을 나눠 동시에 돌리기 위함이다. 출력 계약·few-shot은 verify_system과
    동일하게 쓰며, field는 해당 그룹 값(slide/quiz/voice)으로만 보고하도록 안내한다.
    """
    if group == "slides":
        lines = ["아래 슬라이드 본문만 검수하고 오류만 JSON으로 보고한다. field는 slide로 보고한다.\n"]
        lines.append("[슬라이드 본문]")
        for slide in payload.slides:
            lines.append(f"- slide {slide.slide_idx} (제목={slide.title}): {_plain(slide.html)}")
    elif group == "quizzes":
        lines = ["아래 퀴즈만 검수하고 오류만 JSON으로 보고한다. field는 quiz로 보고한다.\n"]
        lines.append("[퀴즈]")
        for quiz in payload.quizzes:
            answer = quiz.choices[quiz.answer_idx] if 0 <= quiz.answer_idx < len(quiz.choices) else "?"
            lines.append(
                f"- quiz {quiz.slide_idx}: 질문={quiz.question} / 정답={answer} / 해설={quiz.explanation}"
            )
    else:
        lines = ["아래 음성대본의 예시·주장만 검수하고 오류만 JSON으로 보고한다. field는 voice로 보고한다.\n"]
        lines.append("[음성대본]")
        for script in payload.voice_scripts:
            lines.append(f"- voice {script.slide_idx}: {script.script_text}")
    lines.append("\n오류가 없으면 errors를 빈 배열로 둔다. 명백한 오류만 지적한다.")
    return "\n".join(lines)


def correct_system() -> str:
    """교정기 역할·출력 계약을 고정한다. 지목된 오류만 정확히 고쳐 다시 쓴다."""
    return (
        "너는 강의 산출물 교정기다. 검수자가 명백한 오류로 지목한 항목만 올바른 내용으로 "
        "정확히 고쳐 다시 쓴다. 지적되지 않은 부분은 건드리지 않는다. 기존 분량·말투·구조를 "
        "유지하면서 사실·논리만 바로잡는다. 출력은 단일 JSON 객체 하나뿐이며 JSON 외 텍스트, "
        "사고과정, markdown fence, <think> 블록을 금지한다. 최상위 키는 slides, "
        "quiz_explanations, voice_scripts 세 개만 쓰고 요청받은 항목만 채운다. slides[i]는 "
        "slide_idx, html 두 키만 가지며 html은 기존과 같은 <section> 조각 형식을 유지한다. "
        "quiz_explanations[i]는 slide_idx, explanation 두 키만 가진다. voice_scripts[i]는 "
        "slide_idx, script_text 두 키만 가지며 HTML·markdown·괄호 지시문을 넣지 않는다. "
        "고칠 항목이 없는 키는 빈 배열로 둔다."
    )


def correct_user(payload: GeneratedLessonPayload, errors: list[dict[str, object]]) -> str:
    """검출된 오류 목록을 field별로 묶어 교정 지시로 만든다."""
    lines = ["아래는 검수자가 지목한 명백한 오류다. 해당 부분만 올바른 내용으로 정확히 고쳐 다시 쓴다.\n"]
    for err in errors:
        field = str(err.get("field", ""))
        idx = err.get("slide_idx")
        lines.append(
            f"- [{field} {idx}] {err.get('what_is_wrong', '')}\n"
            f"  올바른 내용: {err.get('correction', '')}"
        )
    lines.append("\n[현재 산출물(참고용)]")
    for slide in payload.slides:
        lines.append(f"- slide {slide.slide_idx} html: {slide.html}")
    for quiz in payload.quizzes:
        lines.append(f"- quiz {quiz.slide_idx} explanation: {quiz.explanation}")
    for script in payload.voice_scripts:
        lines.append(f"- voice {script.slide_idx} script_text: {script.script_text}")
    lines.append("\n지적된 항목만 출력하고, 나머지는 빈 배열로 둔다.")
    return "\n".join(lines)


def correct_user_group(
    payload: GeneratedLessonPayload, errors: list[dict[str, object]], group: str
) -> str:
    """한 그룹(slides/quizzes/voice)의 오류만 교정 지시로 만든다(병렬 교정용).

    correct_user와 같은 출력 계약을 쓰되, 참고용 현재 산출물도 해당 그룹만 펼쳐 토큰을
    아끼고 교정기가 다른 그룹을 건드리지 않게 한다.
    """
    field = _group_field(group)
    scoped = [err for err in errors if str(err.get("field", "")) == field]
    lines = [f"아래는 검수자가 지목한 {field}의 명백한 오류다. 해당 부분만 올바른 내용으로 정확히 고쳐 다시 쓴다.\n"]
    for err in scoped:
        idx = err.get("slide_idx")
        lines.append(
            f"- [{field} {idx}] {err.get('what_is_wrong', '')}\n"
            f"  올바른 내용: {err.get('correction', '')}"
        )
    lines.append("\n[현재 산출물(참고용)]")
    _append_group_reference(lines, payload, group)
    lines.append(f"\n지적된 {field} 항목만 출력하고, 나머지 키는 빈 배열로 둔다.")
    return "\n".join(lines)


def _group_field(group: str) -> str:
    if group == "slides":
        return "slide"
    if group == "quizzes":
        return "quiz"
    return "voice"


def _append_group_reference(
    lines: list[str], payload: GeneratedLessonPayload, group: str
) -> None:
    if group == "slides":
        for slide in payload.slides:
            lines.append(f"- slide {slide.slide_idx} html: {slide.html}")
    elif group == "quizzes":
        for quiz in payload.quizzes:
            lines.append(f"- quiz {quiz.slide_idx} explanation: {quiz.explanation}")
    else:
        for script in payload.voice_scripts:
            lines.append(f"- voice {script.slide_idx} script_text: {script.script_text}")


def _plain(html: str) -> str:
    without_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()[:_SLIDE_SUMMARY_CHARS]


__all__ = [
    "correct_system",
    "correct_user",
    "correct_user_group",
    "verify_system",
    "verify_user",
    "verify_user_group",
]
