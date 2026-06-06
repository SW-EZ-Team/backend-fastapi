"""Gemini 로 텍스트 답안을 채점하는 원자적 모듈이다.

IN : assignment_title, assignment_description, assignment_questions, answer_text
OUT: TextGradingResult(score, feedback, ai_confidence)

채점 호출은 동기 google-genai SDK 로 수행한다(상위 핸들러가 asyncio.to_thread 로 감싼다).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from ai_connectors._gemini_common import build_genai_client, google_api_key
from ai_connectors.errors import AIConnectorError

_LOG = logging.getLogger(__name__)

# Gemini 호출 실패 시 반환할 최소 신뢰도
_FALLBACK_CONFIDENCE = 0.0
# 채점용 기본 모델 — .env GEMINI_TEXT_MODEL 로 교체 가능
_DEFAULT_MODEL = "gemini-3.5-flash"


class TextGradingError(RuntimeError):
    """텍스트 채점 과정의 예외를 정규화한다."""


@dataclass(frozen=True)
class TextGradingResult:
    """텍스트 채점 결과 불변 데이터 클래스."""

    # 0~100 점수
    score: int
    # 한국어 피드백
    feedback: str
    # AI 신뢰도 0.0~1.0
    ai_confidence: float


def _build_grading_prompt(
    assignment_title: str,
    assignment_description: str | None,
    assignment_questions: list[str],
    answer_text: str,
) -> str:
    """채점 기준과 답안을 포함한 프롬프트를 조립한다."""
    questions_text = "\n".join(
        f"{i + 1}. {q}" for i, q in enumerate(assignment_questions)
    ) if assignment_questions else "  (문항 정보 없음)"
    criteria = assignment_description or "완성도, 정확성, 내용 충실도를 종합 평가한다."
    return (
        "너는 대학 과제 채점 전문가다. 아래 텍스트 답안을 채점하고 JSON으로만 응답한다.\n\n"
        f"## 과제 정보\n- 제목: {assignment_title}\n"
        f"- 채점 기준: {criteria}\n"
        f"- 문항 목록:\n{questions_text}\n\n"
        "## 학생 답안\n"
        f"{answer_text}\n\n"
        "## 채점 규칙\n"
        "1. 0~100 점수를 부여한다.\n"
        "2. 피드백은 한국어로 구체적이고 건설적으로 작성한다.\n"
        "3. ai_confidence는 채점 확신도(0.0~1.0)를 나타낸다.\n\n"
        "반드시 아래 JSON 형식으로만 응답한다. 다른 텍스트는 포함하지 않는다.\n"
        '{"score":int,"feedback":"str","ai_confidence":float}'
    )


def _parse_grading_json(raw: str) -> TextGradingResult:
    """Gemini 출력에서 JSON을 추출하고 TextGradingResult로 변환한다."""
    # 중괄호 범위만 추출 — 마크다운 코드 블록 포함 가능성 대응
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise TextGradingError("채점 응답에서 JSON을 찾을 수 없다")
    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        raise TextGradingError(f"채점 JSON 파싱 실패: {exc}") from exc

    score_raw = data.get("score", 0)
    confidence_raw = data.get("ai_confidence", _FALLBACK_CONFIDENCE)
    return TextGradingResult(
        score=max(0, min(100, int(score_raw))),
        feedback=str(data.get("feedback", "")),
        ai_confidence=max(0.0, min(1.0, float(confidence_raw))),
    )


def grade_text_submission(
    assignment_title: str,
    assignment_description: str | None,
    assignment_questions: list[str],
    answer_text: str,
    timeout_seconds: int = 90,
) -> TextGradingResult:
    """Gemini 로 텍스트 답안을 채점하고 결과를 반환한다.

    동기 google-genai SDK 로 호출한다(상위 핸들러가 asyncio.to_thread 로 감싼다).
    호출/파싱 실패 시 TextGradingError를 raise한다. timeout_seconds 는 SDK
    HTTP 옵션으로 전달해 무한 대기를 막는다.
    """
    prompt = _build_grading_prompt(
        assignment_title, assignment_description, assignment_questions, answer_text
    )
    _LOG.info("[TextGrader] Gemini 채점 시작 | 답안 길이: %d자", len(answer_text))

    raw_output = _call_gemini(prompt, timeout_seconds)
    if not raw_output:
        raise TextGradingError("Gemini 채점 출력이 비어 있다")

    grading_result = _parse_grading_json(raw_output)
    _LOG.info(
        "[TextGrader] 채점 완료 | score=%d, confidence=%.2f",
        grading_result.score,
        grading_result.ai_confidence,
    )
    return grading_result


def _call_gemini(prompt: str, timeout_seconds: int) -> str:
    """동기 google-genai 호출로 채점 응답 텍스트를 받는다."""
    # API 키 미설정은 즉시 명확한 오류로 전환한다(빈 채점 결과 방지)
    google_api_key()
    try:
        client, genai = build_genai_client()
        model = os.getenv("GEMINI_TEXT_MODEL", _DEFAULT_MODEL)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=1024,
                http_options=genai.types.HttpOptions(timeout=timeout_seconds * 1000),
            ),
        )
    except AIConnectorError as exc:
        raise TextGradingError(f"Gemini 채점 호출 실패: {exc}") from exc
    except Exception as exc:
        raise TextGradingError(f"Gemini 채점 실행 실패: {exc}") from exc

    text = getattr(response, "text", None)
    if not isinstance(text, str):
        raise TextGradingError("Gemini 채점 응답에 텍스트가 없다")
    return text.strip()
