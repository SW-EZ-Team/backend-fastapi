"""Modal GPU 배포용 Qwen3-TTS 네이티브 커넥터.

단건 합성(synthesize), 배치 합성(synthesize_batch),
긴 텍스트 자동 분할+병합, 지수 백오프 재시도를 지원한다.
기본은 배포 클래스의 remote.aio() 네이티브 호출이며,
QWEN3_TTS_MODAL_URL 이 설정되면 Modal 웹 엔드포인트(HTTP multipart) 경로를 쓴다.
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from collections.abc import Sequence
from typing import Protocol
from urllib.parse import unquote

import httpx
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
_DEFAULT_TIMEOUT_SEC = 900.0
_DEFAULT_SEGMENT_CONCURRENCY = 4
_DEFAULT_POOL_SIZE = 6


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
        timeout_sec: float | None = None,
        app_name: str | None = None,
    ) -> None:
        # 명시 endpoint 인자 > QWEN3_TTS_MODAL_URL 환경변수. 값이 있으면 HTTP 경로 활성.
        self._http_url = (endpoint or os.getenv("QWEN3_TTS_MODAL_URL", "")).strip()
        if self._http_url:
            _LOG.info("Qwen3-TTS Modal HTTP 엔드포인트 경로 사용: %s", self._http_url)
        self._app_name = _resolve_app_name(app_name)
        self._timeout_sec = _resolve_timeout_sec(timeout_sec)
        self._segment_concurrency = _resolve_segment_concurrency()
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

        # 여러 세그먼트 — Modal 풀을 고갈시키지 않도록 제한된 병렬 합성 후 병합한다
        started_at = time.perf_counter()
        partial = await self._synthesize_segments_parallel(request, segments)

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

    async def _synthesize_segments_parallel(
        self,
        request: TTSRequest,
        segments: Sequence[str],
    ) -> list[TTSResponse]:
        """분할된 텍스트를 제한된 병렬 호출로 합성하고 원래 순서로 되돌린다."""
        semaphore = asyncio.Semaphore(self._segment_concurrency)
        tasks = [
            asyncio.create_task(
                self._synthesize_segment(
                    index,
                    request.model_copy(update={"text": seg_text}),
                    semaphore,
                )
            )
            for index, seg_text in enumerate(segments)
        ]
        try:
            indexed = await asyncio.gather(*tasks)
        except Exception:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            raise
        return [
            response
            for _index, response in sorted(indexed, key=lambda item: item[0])
        ]

    async def _synthesize_segment(
        self,
        index: int,
        request: TTSRequest,
        semaphore: asyncio.Semaphore,
    ) -> tuple[int, TTSResponse]:
        """단일 세그먼트를 세마포어 안에서 합성해 순서 인덱스와 함께 반환한다."""
        async with semaphore:
            response = await call_with_retry(lambda: self._call_endpoint(request))
        return index, response

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
        """단건 Modal 호출을 실행하고 TTSResponse 로 변환한다.

        QWEN3_TTS_MODAL_URL 이 설정되면 HTTP multipart 경로,
        아니면 기존 네이티브(remote.aio) 경로를 사용한다.
        """
        if self._http_url:
            return await self._call_http_endpoint(request)
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
        except modal.exception.ConnectionError as exc:
            # 연결 불가(엔드포인트 도달 실패)는 백오프 재시도해도 결과가 같다.
            # 재시도 제외 대상(ModelNotFoundError)으로 정규화해 즉시 폴백한다(미리보기 지연 방지).
            raise ModelNotFoundError(
                f"Modal TTS 서버에 연결할 수 없습니다(즉시 폴백): {exc}"
            ) from exc
        except (
            modal.exception.FunctionTimeoutError,
            modal.exception.TimeoutError,
        ) as exc:
            raise ConnectorTimeoutError(f"Modal TTS 실행 시간이 초과되었습니다: {exc}") from exc
        except modal.exception.Error as exc:
            raise InferenceError(f"Modal TTS 네이티브 호출 실패: {exc}") from exc
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        try:
            return build_tts_response_from_modal_result(result, request, self.name, latency_ms)
        except (KeyError, TypeError, ValueError) as exc:
            raise InferenceError(f"Modal TTS 응답 처리 실패: {exc}") from exc

    async def _call_http_endpoint(self, request: TTSRequest) -> TTSResponse:
        """Modal 웹 엔드포인트(synthesize)에 multipart POST 하고 WAV 응답을 변환한다.

        배포된 엔드포인트는 multipart form(text/ref_audio/ref_text/language/speed)을
        받아 audio/wav 바디 + x-* 메타데이터 헤더로 응답한다(modal_tts_app.synthesize).
        303 리다이렉트는 follow_redirects=True 로 흡수한다.
        """
        started_at = time.perf_counter()
        headers: dict[str, str] = {}
        token = os.getenv("QWEN3_TTS_MODAL_TOKEN", "").strip()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        data: dict[str, str] = {
            "text": request.text,
            "language": request.language,
            "speed": str(request.speed),
        }
        if request.ref_text:
            data["ref_text"] = request.ref_text
        files = {"ref_audio": ("ref.wav", request.ref_audio_bytes, "audio/wav")}
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout_sec, follow_redirects=True
            ) as client:
                response = await client.post(
                    self._http_url, data=data, files=files, headers=headers
                )
        except httpx.TimeoutException as exc:
            # ConnectTimeout 도 TimeoutException 하위라 여기로 들어온다 — 일시 지연으로 보고 재시도 유지.
            raise ConnectorTimeoutError(
                f"Modal TTS HTTP 호출 시간이 초과되었습니다: {exc}"
            ) from exc
        except httpx.ConnectError as exc:
            # 연결 거부·DNS 실패(타임아웃 제외) — 백오프 재시도해도 결과가 같다.
            # 재시도 제외 대상(ModelNotFoundError)으로 정규화해 즉시 폴백한다(미리보기 지연 방지).
            raise ModelNotFoundError(
                f"Modal TTS 서버에 연결할 수 없습니다(즉시 폴백): {exc}"
            ) from exc
        except httpx.HTTPError as exc:
            raise InferenceError(f"Modal TTS HTTP 호출 실패: {exc}") from exc
        self._raise_for_http_status(response)
        latency_ms = (time.perf_counter() - started_at) * 1000.0
        return _build_tts_response_from_http(response, request, self.name, latency_ms)

    def _raise_for_http_status(self, response: httpx.Response) -> None:
        """비 2xx HTTP 상태를 공통 커넥터 예외로 정규화한다."""
        if response.is_success:
            return
        detail = response.text[:200]
        status = response.status_code
        if status in {401, 403}:
            raise AuthError(f"Modal TTS HTTP 인증 실패({status}): {detail}")
        if status == 404:
            raise ModelNotFoundError(f"Modal TTS 엔드포인트를 찾을 수 없습니다(404): {detail}")
        if status in {408, 504}:
            raise ConnectorTimeoutError(f"Modal TTS HTTP 타임아웃({status}): {detail}")
        raise InferenceError(f"Modal TTS HTTP 오류({status}): {detail}")


def _build_tts_response_from_http(
    response: httpx.Response,
    request: TTSRequest,
    model_name: str,
    fallback_latency_ms: float,
) -> TTSResponse:
    """웹 엔드포인트의 WAV 바디 + x-* 헤더를 TTSResponse 로 변환한다."""
    audio_bytes = response.content
    if not audio_bytes:
        raise InferenceError("Modal TTS HTTP 응답 본문이 비어 있습니다.")
    headers = response.headers
    ref_text_used = unquote(headers.get("x-ref-text-used", ""))
    return TTSResponse(
        audio_bytes=audio_bytes,
        sample_rate=_header_int(headers, "x-sample-rate", 24000),
        content_type="audio/wav",
        duration_sec=_header_float(headers, "x-duration-sec", 0.0),
        latency_ms=_header_float(headers, "x-latency-ms", fallback_latency_ms),
        char_count=_header_int(headers, "x-char-count", len(request.text)),
        model=model_name,
        auto_transcribed=headers.get("x-auto-transcribed", "false").lower() == "true",
        resolved_ref_text=ref_text_used,
        ref_text_source=headers.get(
            "x-ref-text-source", "client" if ref_text_used else "empty_fallback"
        ),
        retry_count=_header_int(headers, "x-retry-count", 0),
        quality_cer=None,
        quality_reason=headers.get("x-quality-reason", "not_reported"),
        segment_count=_header_int(headers, "x-segment-count", 1),
    )


def _header_int(headers: httpx.Headers, name: str, default: int) -> int:
    """헤더 정수 파싱 실패 시 기본값으로 복구한다."""
    try:
        return int(headers.get(name, str(default)))
    except ValueError:
        return default


def _header_float(headers: httpx.Headers, name: str, default: float) -> float:
    """헤더 실수 파싱 실패 시 기본값으로 복구한다."""
    try:
        return float(headers.get(name, str(default)))
    except ValueError:
        return default


def _resolve_app_name(app_name: str | None) -> str:
    """환경변수의 빈 문자열까지 방어해 Modal 앱 이름을 결정한다."""
    resolved = app_name or os.getenv("QWEN3_TTS_MODAL_APP_NAME", _DEFAULT_APP_NAME)
    return resolved.strip() or _DEFAULT_APP_NAME


def _resolve_timeout_sec(timeout_sec: float | None) -> float:
    """명시 인자 우선, 그다음 환경값, 마지막으로 콜드스타트용 기본값을 사용한다."""
    if timeout_sec is not None:
        return float(timeout_sec)
    return _env_float("QWEN3_TTS_TIMEOUT_SEC", _DEFAULT_TIMEOUT_SEC)


def _resolve_segment_concurrency() -> int:
    """세그먼트 병렬 합성 동시성을 Modal 모델 풀 크기 안으로 제한한다."""
    pool_size = _env_int("QWEN3_TTS_MODAL_POOL_SIZE", _DEFAULT_POOL_SIZE)
    pool_size = _clamp(pool_size, 1, 16)
    concurrency = _env_int("QWEN3_TTS_SEGMENT_CONCURRENCY", _DEFAULT_SEGMENT_CONCURRENCY)
    return _clamp(concurrency, 1, pool_size)


def _env_float(name: str, default: float) -> float:
    """환경변수 float 파싱 실패 시 안전한 기본값으로 복구한다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        _LOG.warning("%s=%r float 파싱 실패 — 기본값 %.1f 사용", name, raw, default)
        return default


def _env_int(name: str, default: int) -> int:
    """환경변수 int 파싱 실패 시 안전한 기본값으로 복구한다."""
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw)
    except ValueError:
        _LOG.warning("%s=%r int 파싱 실패 — 기본값 %d 사용", name, raw, default)
        return default


def _clamp(value: int, min_value: int, max_value: int) -> int:
    """환경 동시성 값이 Modal 풀 한계를 넘지 않게 보정한다."""
    return max(min_value, min(max_value, value))
