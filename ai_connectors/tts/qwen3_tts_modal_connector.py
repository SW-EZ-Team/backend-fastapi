"""Modal GPU 배포용 Qwen3-TTS HTTP 커넥터.

단건 합성(synthesize), 배치 합성(synthesize_batch),
긴 텍스트 자동 분할+병합, 지수 백오프 재시도를 지원한다.
응답 파싱 헬퍼와 재시도 로직은 _modal_retry.py 에 분리되어 있다.
"""
from __future__ import annotations

import asyncio
import os
import time

import httpx

from common.logging import get_logger
from ..errors import AuthError, InferenceError, ModelLoadError, ModelNotFoundError
from ..errors import TimeoutError as ConnectorTimeoutError
from ..tts_schemas import TTSRequest, TTSResponse
from ._text_segmentation import default_segment_pause_ms, split_tts_segments
from ._modal_retry import (
    build_tts_response,
    call_with_retry,
    extract_error_detail,
    merge_segment_responses,
)

_LOG = get_logger(__name__)

# 긴 텍스트를 자동 분할할 때 세그먼트당 최대 문자 수
_SEGMENT_MAX_CHARS = 120


class Qwen3TTSModalConnector:
    """Modal 엔드포인트를 통해 원격 Qwen3-TTS 를 호출한다."""

    name: str = "qwen3-tts-modal"

    def __init__(self, endpoint: str | None = None, timeout_sec: float = 300.0) -> None:
        self._endpoint = endpoint or os.getenv("QWEN3_TTS_MODAL_URL", "").strip()
        self._token = os.getenv("QWEN3_TTS_MODAL_TOKEN", "").strip()
        self._timeout_sec = timeout_sec
        # AsyncClient 를 지연 생성해 재사용한다 — 매 요청마다 TCP 핸드셰이크 방지
        self._client: httpx.AsyncClient | None = None

    # ------------------------------------------------------------------ #
    # 공개 API                                                             #
    # ------------------------------------------------------------------ #

    async def synthesize(self, request: TTSRequest) -> TTSResponse:
        """Modal TTS 엔드포인트에 요청을 보내 WAV 응답을 받는다.

        텍스트가 _SEGMENT_MAX_CHARS 를 초과하면 자동으로 분할 후 병합한다.
        일시적 오류 발생 시 최대 3 회 지수 백오프 재시도한다.
        """
        self._assert_endpoint()
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
        """재사용 중인 AsyncClient 를 명시적으로 닫는다."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def supports(self, feature: str) -> bool:
        """원격 실행 경로에서도 동일한 기능 플래그를 노출한다."""
        return feature in {"voice_cloning", "language_hint", "auto_transcribe", "quality_gate"}

    # ------------------------------------------------------------------ #
    # 내부 메서드                                                          #
    # ------------------------------------------------------------------ #

    def _assert_endpoint(self) -> None:
        """엔드포인트 미설정 시 즉시 예외를 올린다."""
        if not self._endpoint:
            raise ModelLoadError(
                "QWEN3_TTS_MODAL_URL 이 설정되지 않았습니다. "
                "배포 환경에서는 Modal 엔드포인트를 지정하고, "
                "로컬 개발에서는 AI_MODEL_TTS=mlx-audio-qwen3-tts 를 사용하세요."
            )

    def _get_client(self) -> httpx.AsyncClient:
        """AsyncClient 를 지연 생성 후 반환한다."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=self._timeout_sec)
        return self._client

    async def _call_endpoint(self, request: TTSRequest) -> TTSResponse:
        """단건 HTTP 요청을 실행하고 TTSResponse 로 변환한다."""
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        files = {"ref_audio": ("ref.wav", request.ref_audio_bytes, "audio/wav")}
        data: dict[str, str] = {
            "text": request.text,
            "language": request.language,
            "speed": str(request.speed),
        }
        if request.ref_text:
            data["ref_text"] = request.ref_text
        try:
            response = await self._get_client().post(
                self._endpoint, headers=headers, data=data, files=files
            )
        except httpx.TimeoutException as exc:
            raise ConnectorTimeoutError("Modal TTS 응답 시간이 초과되었습니다.") from exc
        except httpx.HTTPError as exc:
            raise InferenceError(f"Modal TTS 호출 실패: {exc}") from exc

        if response.status_code in {401, 403}:
            raise AuthError("Modal TTS 인증에 실패했습니다. 토큰을 확인하세요.")
        if response.status_code == 404:
            raise ModelNotFoundError("Modal TTS 엔드포인트를 찾을 수 없습니다.")
        if response.status_code >= 400:
            raise InferenceError(extract_error_detail(response))

        content_type = response.headers.get("content-type", "audio/wav").split(";")[0]
        if not content_type.startswith("audio/"):
            raise InferenceError("Modal TTS 응답이 오디오 형식이 아닙니다.")

        return build_tts_response(response, request, self.name)
