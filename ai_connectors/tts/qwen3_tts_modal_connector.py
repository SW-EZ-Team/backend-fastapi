"""Modal GPU 배포용 Qwen3-TTS 네이티브 커넥터.

단건 합성(synthesize), 배치 합성(synthesize_batch),
긴 텍스트 자동 분할+병합, 지수 백오프 재시도를 지원한다.
Modal HTTP multipart 대신 배포 클래스의 remote.aio()를 직접 호출한다.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import Protocol

import modal

from common.logging import get_logger
from ..errors import AuthError, InferenceError, ModelNotFoundError
from ..errors import TimeoutError as ConnectorTimeoutError
from ..tts_schemas import TTSRequest, TTSResponse
from ._text_segmentation import default_segment_pause_ms, split_tts_segments
from ._modal_retry import (
    build_tts_response_from_modal_result,
    call_with_retry,
    merge_segment_responses,
)

_LOG = get_logger(__name__)

# 긴 텍스트를 자동 분할할 때 세그먼트당 최대 문자 수
_SEGMENT_MAX_CHARS = 120
_SERVER_CLASS = "Qwen3TTSServer"
_DEFAULT_APP_NAME = "qwen3-tts-modal"


class _RemoteAio(Protocol):
    """Modal remote.aio 호출면만 정의한다."""

    async def aio(self, **payload: object) -> object:
        """Modal 원격 메서드를 비동기로 호출한다."""


class _RemoteMethod(Protocol):
    """Modal 메서드 프록시의 remote 속성을 표현한다."""

    remote: _RemoteAio


class _TtsServer(Protocol):
    """Qwen3TTSServer 에서 커넥터가 쓰는 메서드만 정의한다."""

    synthesize_remote: _RemoteMethod


class Qwen3TTSModalConnector:
    """Modal 배포 클래스 메서드로 원격 Qwen3-TTS 를 호출한다."""

    name: str = "qwen3-tts-modal"

    def __init__(
        self,
        endpoint: str | None = None,
        timeout_sec: float = 300.0,
        app_name: str | None = None,
    ) -> None:
        if endpoint:
            _LOG.warning("기존 HTTP URL 경로는 네이티브 호출에서 사용하지 않습니다.")
        self._app_name = _resolve_app_name(app_name)
        self._timeout_sec = timeout_sec
        # Modal 클래스 조회는 비용이 있으므로 커넥터 인스턴스 안에서 재사용한다.
        self._server: _TtsServer | None = None

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Modal TTS 원격 메서드에 요청을 보내 WAV 응답을 받는다.

        텍스트가 _SEGMENT_MAX_CHARS 를 초과하면 자동으로 분할 후 병합한다.
        일시적 오류 발생 시 최대 3 회 지수 백오프 재시도한다.
        """
        segments = split_tts_segments(request.text, max_chars=_SEGMENT_MAX_CHARS)
        if not segments:
            raise InferenceError("합성할 텍스트가 비어 있습니다.")

        if len(segments) == 1:
            # 단일 세그먼트 — 분할 없이 그대로 전달한다
            return await call_with_retry(lambda: self._call_endpoint(request))

        # 여러 세그먼트 — 순차 합성 후 병합한다
        started_at = time.perf_counter()
        partial: list[TTSResponse] = []
        for seg_text in segments:
            seg_req = request.model_copy(update={"text": seg_text})
            resp = await call_with_retry(lambda r=seg_req: self._call_endpoint(r))
            partial.append(resp)

        sample_rate = partial[0].sample_rate
        first = partial[0]
        return TTSResponse(
            audio_bytes=merge_segment_responses(
                partial,
                sample_rate,
                pause_ms=default_segment_pause_ms(),
            ),
            sample_rate=sample_rate,
            content_type="audio/wav",
            duration_sec=sum(r.duration_sec for r in partial),
            latency_ms=(time.perf_counter() - started_at) * 1000.0,
            char_count=sum(r.char_count for r in partial),
            model=self.name,
            auto_transcribed=first.auto_transcribed,
            resolved_ref_text=first.resolved_ref_text,
            ref_text_source=first.ref_text_source,
            retry_count=sum(r.retry_count for r in partial),
            quality_cer=None,
            quality_reason="not_reported",
            segment_count=len(segments),
        )

    async def synthesize_batch(
        self,
        requests: list[TTSRequest],
        max_concurrency: int = 3,
    ) -> list[TTSResponse | Exception]:
        """여러 TTS 요청을 동시에 처리한다.

        max_concurrency 로 Modal 동시 호출 수를 제한한다.
        하나가 실패해도 나머지는 계속 처리되며,
        결과 리스트에 성공 TTSResponse 또는 예외 객체가 담긴다.
        """
        semaphore = asyncio.Semaphore(max_concurrency)

        async def _bounded(req: TTSRequest) -> TTSResponse | Exception:
            # 세마포어로 Modal 동시 호출 수 제한
            async with semaphore:
                try:
                    return await self.synthesize(req)
                except Exception as exc:
                    # 배치 처리 중 개별 항목 실패는 전파하지 않고 예외 객체로 수집한다
                    _LOG.warning("배치 항목 합성 실패: %s", exc)
                    return exc

        return list(await asyncio.gather(*[_bounded(req) for req in requests]))

    async def aclose(self) -> None:
        """기존 호출부 호환용 무동작 종료 훅이다."""
        self._server = None

    def supports(self, feature: str) -> bool:
        """원격 실행 경로에서도 동일한 기능 플래그를 노출한다."""
        return feature in {"voice_cloning", "language_hint", "auto_transcribe", "quality_gate"}

    def _get_server(self) -> _TtsServer:
        """배포된 Modal 클래스 인스턴스를 지연 생성해 반환한다."""
        if self._server is None:
            server_cls = modal.Cls.from_name(self._app_name, _SERVER_CLASS)
            self._server = server_cls()
        return self._server

    async def _call_endpoint(self, request: TTSRequest) -> TTSResponse:
        """단건 Modal 네이티브 호출을 실행하고 TTSResponse 로 변환한다."""
        started_at = time.perf_counter()
        ref_audio_b64 = base64.b64encode(request.ref_audio_bytes).decode("ascii")
        try:
            result = await asyncio.wait_for(
                self._get_server().synthesize_remote.remote.aio(
                    text=request.text,
                    ref_audio_b64=ref_audio_b64,
                    ref_text=request.ref_text or None,
                    language=request.language,
                    speed=request.speed,
                ),
                timeout=self._timeout_sec,
            )
        except asyncio.TimeoutError as exc:
            raise ConnectorTimeoutError("Modal TTS 네이티브 호출 시간이 초과되었습니다.") from exc
        except modal.exception.NotFoundError as exc:
            raise ModelNotFoundError("Modal TTS 클래스 또는 앱을 찾을 수 없습니다.") from exc
        except modal.exception.AuthError as exc:
            raise AuthError("Modal TTS 인증에 실패했습니다. Modal 토큰을 확인하세요.") from exc
        except (
            modal.exception.ConnectionError,
            modal.exception.FunctionTimeoutError,
            modal.exception.TimeoutError,
        ) as exc:
            raise ConnectorTimeoutError(f"Modal TTS 연결/실행 시간이 초과되었습니다: {exc}") from exc
        except modal.exception.Error as exc:
            raise InferenceError(f"Modal TTS 네이티브 호출 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        try:
            return build_tts_response_from_modal_result(result, request, self.name, latency_ms)
        except (KeyError, TypeError, ValueError) as exc:
            raise InferenceError(f"Modal TTS 응답 처리 실패: {exc}") from exc


def _resolve_app_name(app_name: str | None) -> str:
    """환경변수의 빈 문자열까지 방어해 Modal 앱 이름을 결정한다."""
    resolved = app_name or os.getenv("QWEN3_TTS_MODAL_APP_NAME", _DEFAULT_APP_NAME)
    return resolved.strip() or _DEFAULT_APP_NAME
