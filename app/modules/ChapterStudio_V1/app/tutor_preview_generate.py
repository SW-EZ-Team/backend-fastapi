"""튜터 미리보기 멘트 생성 오케스트레이션.

Spring TutorService.previewTutor 가 호출하는 POST /api/tutors/{tutorId}/preview 의
실제 생성 로직이다. 튜터 설정(말투/속도/깊이/질문방식/이모지/존댓말)을 페르소나
프롬프트로 변환해 ACTIVE_TEXT_MODEL 커넥터(활성 기본 gemini_flash)로 짧은
한국어 미리보기 멘트를 실제 생성한다.

DB 저장은 하지 않는다(프리뷰 전용). 커리큘럼 generate 가 planner 커넥터를 쓰는 것과
동일하게, 여기서는 get_text_connector() 텍스트 커넥터를 재사용한다.
"""
from __future__ import annotations

import logging

from common.llm_output import strip_thinking

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.registry import get_text_connector
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest

_LOG = logging.getLogger(__name__)

_PREVIEW_SYSTEM = (
    "너는 한국어 AI 과외 튜터다. 주어진 페르소나 설정을 그대로 반영해 학생의 샘플 질문에 "
    "답하는 짧은 미리보기 멘트를 만든다. 멘트는 그 튜터가 실제로 수업 중 말하는 한 토막처럼 "
    "자연스러워야 한다. 설명·메타발화·따옴표·코드펜스 없이 멘트 본문만 출력한다."
)

# 빈/실패 출력 시 1회 재시도 후에도 비면 쓰는 폴백 멘트 — 5xx 대신 자연스러운
# 멘트로 사용자 경험을 지킨다(미리보기는 비핵심 기능이라 폴백이 적절).
_FALLBACK_PREVIEW: str = "안녕하세요! 어떤 부분이 궁금한지 편하게 물어봐 주세요. 차근차근 같이 살펴봐요."

# 0~100 슬라이더를 3구간(낮음/중간/높음)으로 나누는 경계값
_LOW_MAX = 33
_HIGH_MIN = 67


def _level(value: int | None) -> int:
    """슬라이더 값을 0(낮음)/1(중간)/2(높음) 구간으로 환산한다. None은 중간."""
    if value is None:
        return 1
    if value <= _LOW_MAX:
        return 0
    if value >= _HIGH_MIN:
        return 2
    return 1


def build_setting_tags(
    tone: int | None,
    speed: int | None,
    depth: int | None,
    question_style: int | None,
    use_emoji: bool | None,
    use_formal_speech: bool | None,
) -> list[str]:
    """슬라이더·토글 설정을 사람이 읽는 한국어 태그 목록으로 변환한다.

    Spring PreviewTutorResponse.settingTags(List<String>)에 그대로 매핑된다.
    """
    tone_words = ("친근한 말투", "균형 잡힌 말투", "차분한 말투")
    speed_words = ("느린 설명 속도", "보통 설명 속도", "빠른 설명 속도")
    depth_words = ("핵심 위주 설명", "적당한 설명 깊이", "깊이 있는 설명")
    question_words = ("직접 알려주는 방식", "적절히 질문하는 방식", "질문을 자주 던지는 방식")

    tags = [
        tone_words[_level(tone)],
        speed_words[_level(speed)],
        depth_words[_level(depth)],
        question_words[_level(question_style)],
    ]
    tags.append("존댓말" if use_formal_speech else "반말")
    tags.append("이모지 사용" if use_emoji else "이모지 미사용")
    return tags


def _build_prompt(sample_question: str, tags: list[str], use_emoji: bool | None) -> str:
    """페르소나 태그와 샘플 질문으로 미리보기 생성 프롬프트를 구성한다."""
    emoji_rule = (
        "문장에 어울리는 이모지를 1~2개 자연스럽게 섞어라."
        if use_emoji
        else "이모지는 절대 쓰지 마라."
    )
    persona = ", ".join(tags)
    return (
        "/no_think\n"
        "아래 페르소나 설정을 가진 AI 과외 튜터가 되어, 학생의 질문에 답하는 미리보기 멘트를 "
        "한국어로 1~3문장(최대 약 150자)으로 작성하라.\n"
        f"페르소나: {persona}\n"
        f"학생 질문: {sample_question}\n"
        f"규칙: {emoji_rule} 멘트 본문만 출력하고 따옴표·설명·머리말은 붙이지 마라."
    )


def _clean(raw: str) -> str:
    """모델 출력에서 thinking 블록·감싼 따옴표·잉여 공백을 제거한다.

    <think> 제거는 공통 유틸 strip_thinking 에 위임한다 — 닫는 태그가 없는 잘린
    Qwen 출력까지 처리해 모듈마다 복붙된 정규식을 없앤다.
    """
    text = strip_thinking(raw)
    # 모델이 멘트 전체를 따옴표로 감싼 경우 한 겹 벗긴다
    if len(text) >= 2 and text[0] in "\"'“”‘’" and text[-1] in "\"'“”‘’":
        text = text[1:-1].strip()
    return text


async def _attempt_preview(prompt: str) -> str:
    """활성 텍스트 커넥터를 한 번 호출해 정제된 미리보기 멘트를 반환한다.

    빈 출력이면 빈 문자열을 그대로 돌려준다 — 재시도 여부는 호출부가 판단한다.
    """
    connector = get_text_connector()
    req = ChapterAIRequest(
        # gemini_flash thinking 토큰(~21000)이 예산을 먼저 잠식한다. 512에서는 thinking만으로 즉시
        # 절단돼 미리보기 멘트가 빈 문자열로 떨어졌다. thinking 헤드룸 확보해 24000으로 올린다
        # (출력은 짧은 멘트라 실제 과금 토큰은 작다).
        system=_PREVIEW_SYSTEM,
        user=prompt,
        max_tokens=24000,
        temperature=0.7,
    )
    resp = await connector.generate(req)
    return _clean(resp.text)


async def generate_tutor_preview(
    sample_question: str,
    tone_slider: int | None,
    speed_slider: int | None,
    depth_slider: int | None,
    question_style_slider: int | None,
    use_emoji: bool | None,
    use_formal_speech: bool | None,
) -> tuple[str, list[str]]:
    """튜터 설정으로 미리보기 멘트를 실제 생성해 (멘트, 설정태그)를 반환한다.

    빈 출력·커넥터 오류가 나면 1회 재시도하고, 그래도 실패하면 폴백 멘트로
    안전하게 응답한다 — 미리보기는 비핵심 기능이라 5xx 보다 폴백이 UX에 낫다.
    """
    tags = build_setting_tags(
        tone_slider,
        speed_slider,
        depth_slider,
        question_style_slider,
        use_emoji,
        use_formal_speech,
    )
    prompt = _build_prompt(sample_question, tags, use_emoji)

    # 1차 시도 → (빈 출력 또는 커넥터 오류면) 1회 재시도 → 그래도 실패면 폴백.
    for attempt in (1, 2):
        try:
            preview_text = await _attempt_preview(prompt)
        except ConnectorError as exc:
            _LOG.warning("[tutor_preview] %d차 호출 실패 — %s", attempt, exc)
            continue
        if preview_text:
            _LOG.info(
                "[tutor_preview] 미리보기 생성 완료(%d차) — %d자, 태그 %d개",
                attempt, len(preview_text), len(tags),
            )
            return preview_text, tags
        _LOG.warning("[tutor_preview] %d차 출력이 비어 있음 — 재시도/폴백 진행", attempt)

    _LOG.error("[tutor_preview] 2회 시도 모두 실패 — 폴백 멘트로 응답한다")
    return _FALLBACK_PREVIEW, tags
