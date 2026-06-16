"""Claude Sonnet(1순위) → Gemini(폴백)로 텍스트 답안을 채점하는 원자적 모듈이다.

IN : assignment_title, assignment_description, assignment_questions, answer_text
OUT: TextGradingResult(score, feedback, ai_confidence)

채점 호출은 동기 SDK 로 수행한다(상위 핸들러가 asyncio.to_thread 로 감싼다).
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

from anthropic import Anthropic

from ai_connectors import _gemini_throttle as _throttle
from ai_connectors._gemini_common import build_genai_client, google_api_key
from ai_connectors.errors import AIConnectorError
from ai_connectors.text.claude_sonnet_connector import _first_text_block
from common.text_config import claude_sonnet_api_key, claude_sonnet_model

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
        f"- 과제 설명·채점 기준: {criteria}\n"
        f"- 문항 목록:\n{questions_text}\n\n"
        "## 학생 답안\n"
        f"{answer_text}\n\n"
        "## 채점 규칙\n"
        "1. 점수(0~100)는 반드시 다음 세 기준의 합으로 산출한다 — "
        "정확성(과제 요구와 문항에 맞는 올바른 내용인가, 40점) / "
        "완성도(요구 항목을 빠짐없이 다뤘고 분량·형식이 충분한가, 30점) / "
        "논리(주장-근거-예시가 일관되게 연결되는가, 30점). "
        "기준별 감점 사유를 피드백에 반영한다.\n"
        "2. 피드백은 한국어 2~4문장 이상으로, 반드시 다음 세 가지를 모두 담는다: "
        "잘한 점(답안에서 실제로 잘 쓴 부분을 구체적으로 인용), "
        "부족한 점(어떤 문항·기준에서 무엇이 빠졌거나 틀렸는지), "
        "개선 방법(다음에 어떻게 보완하면 되는지 실행 가능한 조언). "
        "과제 문항 내용을 직접 언급하며 작성하고, '잘했어요/노력하세요' 같은 두루뭉술한 표현만으로 끝내지 않는다.\n"
        "3. 답안이 과제 문항과 무관하거나 비어 있으면 정확성 0점 처리하고 그 이유를 피드백에 명시한다.\n"
        "4. ai_confidence는 채점 확신도(0.0~1.0)를 나타낸다 — 답안이 모호하거나 "
        "문항 정보가 부족할수록 낮춘다.\n\n"
        "반드시 아래 JSON 형식으로만 응답한다. 다른 텍스트는 포함하지 않는다.\n"
        '{"score":int,"feedback":"str","ai_confidence":float}'
    )


def _parse_grading_json(raw: str) -> TextGradingResult:
    """Gemini 출력에서 JSON을 추출하고 TextGradingResult로 변환한다.

    gemini-3.5-flash 등 reasoning 모델은 본문 앞에 <think> 블록·영문 서문을 흘리므로,
    먼저 strip_thinking 으로 reasoning 을 제거한 뒤 중괄호 범위를 추출한다.
    (2026-06-14 실측: 추론 토큰이 응답을 잠식해 JSON 중괄호 자체가 안 나오던 채점 실패 수정.)
    """
    from common.llm_output import strip_thinking

    raw = strip_thinking(raw)
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
    """Claude Sonnet → Gemini 폴백으로 텍스트 답안을 채점하고 결과를 반환한다.

    동기 SDK 로 호출한다(상위 핸들러가 asyncio.to_thread 로 감싼다).
    호출/파싱 실패 시 TextGradingError를 raise한다. timeout_seconds 는 SDK
    HTTP 옵션으로 전달해 무한 대기를 막는다.
    """
    prompt = _build_grading_prompt(
        assignment_title, assignment_description, assignment_questions, answer_text
    )
    _LOG.info("[TextGrader] Claude 채점 시작 | 답안 길이: %d자", len(answer_text))

    raw_output: str | None = None
    try:
        raw_output = _call_claude(prompt, timeout_seconds)
    except Exception as exc:
        _LOG.warning("[TextGrader] Claude 채점 실패, Gemini 폴백 | %s", exc)
        raw_output = _call_gemini(prompt, timeout_seconds)
    if not raw_output:
        raise TextGradingError("채점 출력이 비어 있다")

    grading_result = _parse_grading_json(raw_output)
    _LOG.info(
        "[TextGrader] 채점 완료 | score=%d, confidence=%.2f",
        grading_result.score,
        grading_result.ai_confidence,
    )
    return grading_result


def _call_claude(prompt: str, timeout_seconds: int) -> str:
    """동기 Anthropic 호출로 채점 응답 텍스트를 받는다."""
    api_key = claude_sonnet_api_key()
    if api_key is None:
        raise TextGradingError("CLAUDE_SONNET_API_KEY 또는 ANTHROPIC_API_KEY가 설정되지 않았다.")
    try:
        client = Anthropic(api_key=api_key, timeout=timeout_seconds)
        msg = client.messages.create(
            model=claude_sonnet_model(),
            max_tokens=8192,
            temperature=0.0,
            messages=[{"role": "user", "content": prompt}],
        )
    except Exception as exc:
        raise TextGradingError(f"Claude 채점 호출 실패: {exc}") from exc

    return _first_text_block(msg).strip()


def _call_gemini(prompt: str, timeout_seconds: int) -> str:
    """동기 google-genai 호출로 채점 응답 텍스트를 받는다."""
    # API 키 미설정은 즉시 명확한 오류로 전환한다(빈 채점 결과 방지)
    google_api_key()
    # 프로세스 전역 Gemini 호출 간격 스로틀 — 시험 생성·강의 생성과 동시 실행 시
    # 429/503 폭주를 막는다(동기 경로이므로 sync 변형 사용, to_thread 안에서 안전).
    _throttle.wait_for_slot_sync()
    try:
        client, genai = build_genai_client()
        model = os.getenv("GEMINI_TEXT_MODEL", _DEFAULT_MODEL)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=genai.types.GenerateContentConfig(
                temperature=0.0,
                # reasoning 모델(gemini-3.5-flash)은 thinking 토큰을 먼저 소비하므로
                # 1024는 채점 JSON이 출력되기 전에 소진됐다. thinking + 소형 JSON 모두
                # 담기도록 넉넉히 둔다(목표 출력은 작아 실제 소모는 thinking 분량뿐).
                max_output_tokens=8192,
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
