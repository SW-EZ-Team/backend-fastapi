"""Claude Sonnet VLM으로 과제 파일을 채점하는 원자적 모듈이다."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from dataclasses import field

from anthropic import AsyncAnthropic

from ..config import GRADING_TIMEOUT_SECONDS
from ..config import get_grading_api_key
from ..config import get_grading_model


class GradingError(RuntimeError):
    """채점 과정의 예외를 정규화한다."""


@dataclass(frozen=True)
class DetectedWeakness:
    """채점 중 발견된 단일 약점 항목이다."""

    topic: str
    subtopic: str
    error_pattern: str
    severity: int  # 1~5


@dataclass(frozen=True)
class GradingResult:
    """Claude VLM 채점 결과를 담는 불변 데이터 클래스다."""

    score: int  # 0~100
    feedback: str  # 한국어 피드백
    confidence: float  # 0.0~1.0
    weaknesses: list[DetectedWeakness] = field(default_factory=list)
    error_type: str | None = None  # 계산/개념/공식/해석/없음


# 파일 확장자 → MIME 타입 매핑
_MEDIA_TYPE_MAP: dict[str, str] = {
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "pdf": "application/pdf",
}


def _resolve_media_type(file_name: str) -> str:
    """파일명 확장자로 MIME 타입을 결정한다."""
    ext = file_name.rsplit(".", 1)[-1].lower() if "." in file_name else ""
    return _MEDIA_TYPE_MAP.get(ext, "image/jpeg")


def _build_system_prompt(
    assignment_title: str,
    assignment_steps: list[str],
    assignment_rubric: list[str],
) -> str:
    """채점 기준을 포함한 시스템 프롬프트를 조립한다."""
    steps_text = "\n".join(f"{i + 1}. {s}" for i, s in enumerate(assignment_steps))
    rubric_text = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(assignment_rubric))
    return (
        "너는 대학 수준의 과제 채점 전문가다. 학생이 제출한 파일을 다음 기준으로 채점한다.\n\n"
        f"## 과제 정보\n- 제목: {assignment_title}\n"
        f"- 수행 단계:\n{steps_text}\n"
        f"- 채점 기준:\n{rubric_text}\n\n"
        "## 채점 규칙\n"
        "1. 0~100점 스케일로 채점한다\n"
        "2. 각 루브릭 항목별 부분 점수를 합산한다\n"
        "3. 약점이 발견되면 topic/subtopic/error_pattern/severity(1~5)로 분류한다\n"
        "4. 주요 오류 유형을 하나 선택한다: 계산/개념/공식/해석/없음\n"
        "5. 피드백은 한국어로 구체적으로 작성한다\n\n"
        '반드시 다음 JSON 형식으로만 응답한다:\n'
        '{"score":int,"feedback":"str","confidence":float,'
        '"weaknesses":[{"topic":"str","subtopic":"str","error_pattern":"str","severity":int}],'
        '"error_type":"str|null"}'
    )


def _build_content_block(file_bytes: bytes, file_name: str) -> list[object]:
    """파일 종류에 따라 Anthropic vision 또는 document content block을 만든다."""
    media_type = _resolve_media_type(file_name)
    encoded = base64.standard_b64encode(file_bytes).decode("ascii")
    if media_type.startswith("image/"):
        # 이미지는 image content block으로 전달한다
        return [{"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}}]
    # PDF는 document content block으로 전달한다
    return [{"type": "document", "source": {"type": "base64", "media_type": media_type, "data": encoded}}]


def _parse_grading_json(raw: str) -> GradingResult:
    """VLM 응답 문자열에서 JSON을 추출하고 GradingResult로 변환한다."""
    # 마크다운 코드 블록이 포함될 수 있으므로 중괄호 범위를 직접 찾는다
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        raise GradingError("채점 응답에서 JSON을 찾을 수 없다")
    try:
        data = json.loads(raw[start:end])
    except json.JSONDecodeError as exc:
        raise GradingError(f"채점 JSON 파싱 실패: {exc}") from exc

    weaknesses = [
        DetectedWeakness(
            topic=str(w.get("topic", "")),
            subtopic=str(w.get("subtopic", "")),
            error_pattern=str(w.get("error_pattern", "")),
            severity=int(w.get("severity", 1)),
        )
        for w in data.get("weaknesses", [])
        if isinstance(w, dict)
    ]
    return GradingResult(
        score=int(data.get("score", 0)),
        feedback=str(data.get("feedback", "")),
        confidence=float(data.get("confidence", 0.0)),
        weaknesses=weaknesses,
        error_type=data.get("error_type") or None,
    )


async def grade_submission(
    file_bytes: bytes,
    file_name: str,
    assignment_title: str,
    assignment_steps: list[str],
    assignment_rubric: list[str],
) -> GradingResult:
    """Claude Sonnet VLM으로 과제 파일을 채점하고 결과를 반환한다."""
    api_key = get_grading_api_key()
    if api_key is None:
        raise GradingError("ANTHROPIC_API_KEY 환경변수가 설정되지 않았다")

    client = AsyncAnthropic(api_key=api_key, timeout=float(GRADING_TIMEOUT_SECONDS))
    system_prompt = _build_system_prompt(assignment_title, assignment_steps, assignment_rubric)
    content_blocks = _build_content_block(file_bytes, file_name)
    # 채점 지시를 텍스트 블록으로 추가한다
    content_blocks.append({"type": "text", "text": "위 파일을 채점하고 지정된 JSON 형식으로 결과를 반환하라."})

    try:
        msg = await client.messages.create(
            model=get_grading_model(),
            max_tokens=1024,
            temperature=0.0,
            system=system_prompt,
            messages=[{"role": "user", "content": content_blocks}],
        )
        await client.close()
    except Exception as exc:
        await client.close()
        raise GradingError(f"Claude API 호출 실패: {exc}") from exc

    raw_text = _extract_text(msg)
    return _parse_grading_json(raw_text)


def _extract_text(msg: object) -> str:
    """Anthropic 응답 객체에서 첫 번째 텍스트 블록을 꺼낸다."""
    content = getattr(msg, "content", ())
    if not content:
        raise GradingError("채점 응답이 비어 있다")
    first = content[0]
    text = getattr(first, "text", None)
    if not isinstance(text, str) or not text.strip():
        raise GradingError("채점 응답 텍스트 블록이 없다")
    return text
