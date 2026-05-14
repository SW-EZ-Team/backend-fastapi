from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Mapping, Sequence

import modal

from app.modules.ChapterStudio_V1.ai_connectors.errors import AuthError, ConnectorError
from app.modules.ChapterStudio_V1.ai_connectors.errors import TimeoutError as ConnectorTimeoutError
from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse
from app.modules.ChapterStudio_V1.common.config import qwen_app_name

_MODEL_NAME = "Qwen/Qwen3.6-27B-FP8"
_SERVER_CLASS = "Qwen27BServer"
_TIMEOUT_SEC = 900.0
_MAX_REMOTE_INPUTS = 8


class Qwen27BModalConnector:
    name = "qwen27b_modal"

    def __init__(self) -> None:
        # Modal 1.x class lookup은 배포된 vLLM 서버 클래스와 1:1로 연결된다.
        server_cls = modal.Cls.from_name(qwen_app_name(), _SERVER_CLASS)
        self._server = server_cls()

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """단일 슬라이드 컨텍스트를 Modal vLLM 함수로 전달한다."""
        try:
            result = await _with_timeout(
                self._server.generate.remote.aio(
                    system=req.system,
                    user=req.user,
                    max_tokens=req.max_tokens,
                    temperature=req.temperature,
                    extra=req.extra,
                )
            )
            return _response_from_mapping(_as_mapping(result))
        except (modal.exception.ConnectionError, modal.exception.TimeoutError) as e:
            raise ConnectorTimeoutError(str(e)) from e
        except modal.exception.AuthError as e:
            raise AuthError(str(e)) from e
        except (RuntimeError, TypeError, KeyError, ValueError) as e:
            raise ConnectorError(f"Qwen27B 호출 실패: {e}") from e

    async def generate_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        """Modal concurrent input을 8개 단위로 써서 B200 과확장을 막는다."""
        if not reqs:
            return []
        responses: list[ChapterAIResponse] = []
        for chunk in _chunks(reqs, _MAX_REMOTE_INPUTS):
            responses.extend(await asyncio.gather(*[self.generate(r) for r in chunk]))
        return responses

    def supports(self, feature: str) -> bool:
        return feature in {"batch", "long_context"}

    async def _generate_modal_batch(
        self, reqs: list[ChapterAIRequest]
    ) -> list[ChapterAIResponse]:
        try:
            results = await _with_timeout(
                self._server.generate_batch.remote.aio(batch=[_request_payload(r) for r in reqs])
            )
            return [_response_from_mapping(item) for item in _as_mapping_list(results)]
        except (modal.exception.ConnectionError, modal.exception.TimeoutError) as e:
            raise ConnectorTimeoutError(str(e)) from e
        except modal.exception.AuthError as e:
            raise AuthError(str(e)) from e
        except (RuntimeError, TypeError, KeyError, ValueError) as e:
            raise ConnectorError(f"Qwen27B 배치 호출 실패: {e}") from e


def _request_payload(req: ChapterAIRequest) -> dict[str, object]:
    return {
        "system": req.system,
        "user": req.user,
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
        "extra": req.extra,
    }


async def _with_timeout(awaitable: Awaitable[object]) -> object:
    try:
        return await asyncio.wait_for(awaitable, timeout=_TIMEOUT_SEC)
    except asyncio.TimeoutError as exc:
        raise ConnectorTimeoutError(f"Qwen27B 호출 {int(_TIMEOUT_SEC)}초 타임아웃") from exc


def _chunks(reqs: list[ChapterAIRequest], size: int) -> list[list[ChapterAIRequest]]:
    if size < 1:
        raise ValueError("배치 크기는 1 이상이어야 한다.")
    return [reqs[index:index + size] for index in range(0, len(reqs), size)]


def _as_mapping(result: object) -> Mapping[str, object]:
    if not isinstance(result, Mapping):
        raise TypeError("Modal 응답이 mapping 형식이 아니다.")
    return result


def _as_mapping_list(result: object) -> list[Mapping[str, object]]:
    if not isinstance(result, Sequence) or isinstance(result, str):
        raise TypeError("Modal 배치 응답이 sequence 형식이 아니다.")
    return [_as_mapping(item) for item in result]


def _response_from_mapping(data: Mapping[str, object]) -> ChapterAIResponse:
    return ChapterAIResponse(
        text=_as_str(data["text"]),
        model=_as_str(data.get("model", _MODEL_NAME)),
        input_tokens=_as_int(data["input_tokens"]),
        output_tokens=_as_int(data["output_tokens"]),
        finish_reason=_as_str(data["finish_reason"]),
    )


def _as_str(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("문자열 필드가 올바르지 않다.")
    return value


def _as_int(value: object) -> int:
    if not isinstance(value, int):
        raise TypeError("정수 필드가 올바르지 않다.")
    return value
