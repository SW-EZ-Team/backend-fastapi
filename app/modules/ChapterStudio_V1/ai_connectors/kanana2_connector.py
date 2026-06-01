from __future__ import annotations

import asyncio
import re

import modal

from app.modules.ChapterStudio_V1.common.config import kanana_app_name
from app.modules.ChapterStudio_V1.common.logging import logger
from common.llm_output import clean_llm_text

_SERVER_CLASS = "Kanana2Server"
_TIMEOUT_SEC = 300.0
_PREFIX_RE = re.compile(r"^(?:교정된\s*본문|수정된\s*본문|교정\s*결과|결과|답변)\s*[:：]\s*")


class Kanana2Connector:
    name = "kanana2_polish"

    def __init__(self) -> None:
        # 배포 앱 이름만 환경변수로 바꿔 같은 호출 코드를 로컬/운영에서 재사용한다.
        server_cls = modal.Cls.from_name(kanana_app_name(), _SERVER_CLASS)
        self._server = server_cls()

    async def polish(self, text: str, *, tone_hint: str = "") -> str:
        """교정 실패가 강의 생성을 막지 않도록 원문을 보존한다."""
        if text == "":
            return text
        instruction = _instruction(tone_hint)
        try:
            result = await asyncio.wait_for(
                self._server.correct.remote.aio(text=text, instruction=instruction),
                timeout=_TIMEOUT_SEC,
            )
            cleaned = _clean_output(str(result))
            return cleaned if cleaned else text
        except asyncio.TimeoutError:
            logger.warning("Kanana2 polish: {}초 타임아웃으로 원문 유지", int(_TIMEOUT_SEC))
            return text
        except (modal.exception.ConnectionError, modal.exception.TimeoutError) as exc:
            logger.warning("Kanana2 polish: Modal 연결 실패로 원문 유지: {}", exc)
            return text
        except modal.exception.AuthError as exc:
            logger.warning("Kanana2 polish: Modal 인증 실패로 원문 유지: {}", exc)
            return text
        except (RuntimeError, TypeError, ValueError, KeyError) as exc:
            logger.warning("Kanana2 polish: 응답 처리 실패로 원문 유지: {}", exc)
            return text


def _instruction(tone_hint: str) -> str:
    base = (
        "너는 한국어 교정 전문가다. 최우선 규칙: 입력 텍스트에 한자·중국어·일본어 등 "
        "비한국어 문자가 섞여 있으면 반드시 자연스러운 한국어로 바꾼다. "
        "이때 길이가 바뀌어도 무조건 바꾼다. 맞춤법·표준어 오류도 표준 표기로 고치고, "
        "교정에 필요한 만큼 길이가 바뀌어도 된다. 띄어쓰기와 문장부호도 고쳐라 "
        "(의문문 끝 물음표 등). 의미와 말투(반말/존댓말)는 유지한다. "
        "새 문장 추가·요약·삭제 금지. 문장 순서 유지. 원문에 오류가 없으면 그대로 둔다.\n"
        "- 입력: \"음수와 양수가 공존하는 정수的世界里에서 수직선은\" → 출력: "
        "\"음수와 양수가 공존하는 정수의 세계에서 수직선은\"\n"
        "- 입력: \"음수의 절대값이 크다고 해서\" → 출력: \"음수의 절댓값이 크다고 해서\"\n"
        "- 입력: \"비교할 수 있을까요 스스로 질문하며\" → 출력: "
        "\"비교할 수 있을까요? 스스로 질문하며\"\n"
        "설명 없이 교정된 본문만 출력."
    )
    if tone_hint:
        return f"{base} 말투는 {tone_hint} 유지."
    return base


def _clean_output(raw: str) -> str:
    """모델이 붙인 짧은 머리말만 제거하고 본문은 그대로 둔다."""
    text = clean_llm_text(raw).strip()
    return _PREFIX_RE.sub("", text).strip()


__all__ = ["Kanana2Connector"]
