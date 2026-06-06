"""강의 산출물 단일 targeted-repair.

self-check(quality.py)가 찾은 미달 항목만 모아 한 번의 추가 LLM 호출로 해당 부분만 다시
생성한다. eval 스크립트(run_modal_actual_lesson_eval)에서 검증된 voice 확장·supporting 보강
패턴을 프로덕션 모듈로 승격한 것이며, 새 발명은 하지 않는다.

설계 원칙:
    - repair는 "최대 1회"다. 미달이 남아도 원본을 유지(graceful)하고 절대 예외로 죽지 않는다.
    - 병합 후 slide_idx 집합 계약을 재검증한다(인덱스 깨짐 방지). 깨지면 원본을 되돌린다.
    - voice/explanation/note만 손댄다. 슬라이드 HTML·인덱스·키 계약은 불변이다.

공개 API:
    - repair_payload(connector, payload, report, slide_count) : 보강된 payload(또는 원본)를 반환.
"""
from __future__ import annotations

import json
import re
from html import unescape

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.base import AIConnector
from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest
from app.modules.ChapterStudio_V1.pipeline.payload import (
    GeneratedLessonPayload,
    GeneratedQuiz,
    GeneratedSlide,
    GeneratedVoiceScript,
)
from app.modules.ChapterStudio_V1.pipeline.quality import QualityReport
from common.llm_output import extract_json_block, strip_thinking

# repair 호출당 토큰 상한 — voice 한 묶음 + supporting을 한 번에 받을 수 있는 여유값.
# gemini-3.5-flash는 thinking 토큰(실측 0~21000 변동)이 max_output_tokens 예산을 먼저
# 잠식한다. 16000에서는 thinking이 크면 voice 보강 JSON 본문이 절단돼(finish_reason=MAX_TOKENS)
# repair 전체가 ConnectorError로 실패했다. thinking(~21000) + voice 묶음 본문에 여유를 더해
# 40000으로 올린다(메인 생성노드 prompt.py=48000과 동일 기준, 모델 한도 65536 이내).
_REPAIR_MAX_TOKENS = 40000


class _VoiceRepairItem(BaseModel):
    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=14)
    script_text: str = Field(min_length=40)


class _QuizExplanationItem(BaseModel):
    model_config = ConfigDict(strict=True)

    slide_idx: int = Field(ge=0, le=14)
    explanation: str = Field(min_length=30)


class _RepairResult(BaseModel):
    """repair 응답 — 보강한 항목만 부분적으로 담는다(없으면 빈 배열)."""

    model_config = ConfigDict(strict=True)

    voice_scripts: list[_VoiceRepairItem] = Field(default_factory=list)
    quiz_explanations: list[_QuizExplanationItem] = Field(default_factory=list)


async def repair_payload(
    connector: AIConnector,
    payload: GeneratedLessonPayload,
    report: QualityReport,
    slide_count: int,
) -> GeneratedLessonPayload:
    """미달 항목을 1회 targeted-repair로 보강한 payload를 반환한다(실패 시 원본 유지)."""
    if report.is_ok():
        return payload
    request = _repair_request(payload, report)
    try:
        response = await connector.generate(request)
        result = _parse_repair(response.text)
    except (ConnectorError, ValueError, ValidationError, json.JSONDecodeError):
        # repair 응답이 깨지거나(파싱 실패) 커넥터가 실패하면(절단 MAX_TOKENS·타임아웃·rate limit 등
        # ConnectorError) 보강을 포기하고 원본을 그대로 쓴다(graceful, silent 빈출력 아님).
        # ConnectorError를 빠뜨리면 절단 가드가 올린 예외가 stage 전체를 죽인다(docstring 계약 위반).
        return payload
    merged = _merge(payload, result)
    if not _indices_intact(merged, slide_count):
        # 병합이 인덱스 계약을 깨뜨렸다면 원본으로 되돌린다.
        return payload
    return merged


def _repair_request(payload: GeneratedLessonPayload, report: QualityReport) -> ChapterAIRequest:
    voice_targets = sorted(report.voice_targets())
    quiz_targets = sorted({d.slide_idx for d in report.deficiencies if d.field == "explanation"})
    note_low = any(d.field == "note" for d in report.deficiencies)
    return ChapterAIRequest(
        system=_repair_system(),
        user=_repair_user(payload, voice_targets, quiz_targets, note_low),
        max_tokens=_REPAIR_MAX_TOKENS,
        temperature=0.2,
        extra={"slide_count": len(payload.slides), "schema": "lesson_repair", "lesson_repair": True},
    )


def _repair_system() -> str:
    return (
        "너는 ChapterStudio_V1의 강의 산출물 보강기다. 출력은 단일 JSON 객체 한 개뿐이다. "
        "JSON 외 텍스트, 사고과정, markdown fence, <think> 블록을 금지한다. "
        "최상위 키는 voice_scripts, quiz_explanations 두 개만 쓰고, 요청받은 항목만 채운다. "
        "voice_scripts[i]는 slide_idx, script_text 두 키만 가진다. "
        "script_text는 900~1600자, 8~12문장의 과외 선생님 말투 대본이며 화면에 없는 깊은 설명, "
        "실수하기 쉬운 지점, 바로 해볼 미니연습을 자연스러운 존댓말 한 문단으로 담는다. "
        "HTML 태그, markdown, 괄호 지시문, 글머리표를 넣지 않는다. "
        "quiz_explanations[i]는 slide_idx, explanation 두 키만 가진다. "
        "explanation은 120~180자로 정답 이유와 오답 함정을 함께 적고 약점 개념과 연결한다."
    )


def _repair_user(
    payload: GeneratedLessonPayload,
    voice_targets: list[int],
    quiz_targets: list[int],
    note_low: bool,
) -> str:
    lines = [
        "다음 강의의 일부 산출물이 분량·품질 기준에 미달한다. 미달 항목만 다시 쓴다. "
        "핵심 규칙: 기존 초안을 줄이지 말고, 기존 내용을 유지·확장해 더 길고 깊게 만든다. 같은 문장 반복은 금지한다.\n"
    ]
    if voice_targets:
        lines.append(f"음성대본을 보강할 slide_idx: {voice_targets} (각 900자 이상, 900자 미만이면 실패)")
        for idx in voice_targets:
            slide = _slide_by_idx(payload, idx)
            current = _voice_by_idx(payload, idx)
            if slide is None or current is None:
                continue
            lines.append(
                f"- slide {idx}({len(current)}자): 제목={slide.title} / 초점={slide.focus} / "
                f"화면요약={_slide_summary(slide.html)}\n  기존 초안: {current}"
            )
    if quiz_targets:
        lines.append(f"\n퀴즈 해설을 보강할 slide_idx: {quiz_targets} (각 120자 이상, 오답 함정과 약점 연결 포함)")
        for idx in quiz_targets:
            quiz = _quiz_by_idx(payload, idx)
            if quiz is not None:
                lines.append(
                    f"- slide {idx}: 질문={quiz.question} / 정답보기={quiz.choices[quiz.answer_idx]}\n"
                    f"  기존 해설({len(quiz.explanation)}자): {quiz.explanation}"
                )
    if note_low:
        lines.append("\n(참고) note bullet이 얕았으니 해설·대본을 더 구체적으로 쓴다.")
    lines.append("\n요청하지 않은 slide_idx는 출력에서 제외한다. 빈 항목은 빈 배열로 둔다.")
    return "\n".join(lines)


def _slide_summary(html: str) -> str:
    plain = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", unescape(plain)).strip()[:240]


def _quiz_by_idx(payload: GeneratedLessonPayload, slide_idx: int) -> GeneratedQuiz | None:
    for quiz in payload.quizzes:
        if quiz.slide_idx == slide_idx:
            return quiz
    return None


def _voice_by_idx(payload: GeneratedLessonPayload, slide_idx: int) -> str | None:
    for script in payload.voice_scripts:
        if script.slide_idx == slide_idx:
            return script.script_text
    return None


def _slide_by_idx(payload: GeneratedLessonPayload, slide_idx: int) -> GeneratedSlide | None:
    for slide in payload.slides:
        if slide.slide_idx == slide_idx:
            return slide
    return None


def _parse_repair(text: str) -> _RepairResult:
    block = extract_json_block(strip_thinking(text))
    return _RepairResult.model_validate_json(block)


def _merge(payload: GeneratedLessonPayload, result: _RepairResult) -> GeneratedLessonPayload:
    voice_by_idx = {item.slide_idx: item.script_text for item in result.voice_scripts}
    expl_by_idx = {item.slide_idx: item.explanation for item in result.quiz_explanations}
    new_voice = [
        GeneratedVoiceScript(slide_idx=v.slide_idx, script_text=voice_by_idx.get(v.slide_idx, v.script_text))
        for v in payload.voice_scripts
    ]
    new_quizzes = [
        q.model_copy(update={"explanation": expl_by_idx[q.slide_idx]}) if q.slide_idx in expl_by_idx else q
        for q in payload.quizzes
    ]
    return payload.model_copy(update={"voice_scripts": new_voice, "quizzes": new_quizzes})


def _indices_intact(payload: GeneratedLessonPayload, slide_count: int) -> bool:
    expected = set(range(slide_count))
    voice_idx = {script.slide_idx for script in payload.voice_scripts}
    quiz_idx = {quiz.slide_idx for quiz in payload.quizzes}
    slide_idx = {slide.slide_idx for slide in payload.slides}
    return voice_idx == expected and quiz_idx == expected and slide_idx == expected


__all__ = ["repair_payload"]
