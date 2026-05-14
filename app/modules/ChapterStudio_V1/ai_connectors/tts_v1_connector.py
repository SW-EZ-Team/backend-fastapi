from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from time import time
from uuid import uuid4

import httpx

from app.modules.ChapterStudio_V1.ai_connectors.errors import ConnectorError, TimeoutError
from app.modules.ChapterStudio_V1.common.config import tts_endpoint, tts_output_dir, tts_ref_audio_path, tts_ref_text, tts_timeout_sec


class TTSV1Connector:
    name = "tts_v1"

    def __init__(self) -> None:
        endpoint = tts_endpoint()
        if endpoint is None:
            raise ConnectorError("TTS_ENDPOINT가 설정되지 않았다.")
        self._endpoint = endpoint
        self._ref_audio_path = tts_ref_audio_path()
        self._ref_text = tts_ref_text()
        self._output_dir = tts_output_dir()
        self._client = httpx.AsyncClient(timeout=tts_timeout_sec())

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, str | float]:
        if self._ref_audio_path is not None:
            return await self._synthesize_audio_endpoint(text, voice)
        return await self._synthesize_json_endpoint(text, voice)

    async def _synthesize_json_endpoint(self, text: str, voice: str) -> dict[str, str | float]:
        try:
            response = await self._client.post(
                self._endpoint,
                json={"text": text, "voice": voice},
            )
            response.raise_for_status()
            return _validated_payload(response.json())
        except httpx.TimeoutException as e:
            raise TimeoutError(f"TTS V1 타임아웃: {e}") from e
        except httpx.HTTPStatusError as e:
            raise ConnectorError(f"TTS V1 HTTP 오류 {e.response.status_code}: {e}") from e
        except httpx.HTTPError as e:
            raise ConnectorError(f"TTS V1 호출 실패: {e}") from e

    async def _synthesize_audio_endpoint(self, text: str, voice: str) -> dict[str, str | float]:
        ref_path = self._validated_ref_audio_path()
        try:
            response = await self._client.post(
                self._endpoint,
                data=_audio_form_data(text, voice, self._ref_text),
                files={"ref_audio": (ref_path.name, ref_path.read_bytes(), _media_type(ref_path))},
            )
            response.raise_for_status()
            return _saved_audio_payload(response, self._output_dir, voice, text)
        except httpx.TimeoutException as e:
            raise TimeoutError(f"TTS V1 타임아웃: {e}") from e
        except httpx.HTTPStatusError as e:
            raise ConnectorError(f"TTS V1 HTTP 오류 {e.response.status_code}: {e}") from e
        except httpx.HTTPError as e:
            raise ConnectorError(f"TTS V1 호출 실패: {e}") from e
        except OSError as e:
            raise ConnectorError(f"TTS V1 오디오 파일 처리 실패: {e}") from e

    def _validated_ref_audio_path(self) -> Path:
        if self._ref_audio_path is None:
            raise ConnectorError("TTS_REF_AUDIO_PATH가 설정되지 않았다.")
        if not self._ref_audio_path.exists() or not self._ref_audio_path.is_file():
            raise ConnectorError("TTS_REF_AUDIO_PATH 파일을 찾을 수 없다.")
        return self._ref_audio_path

    def supports(self, feature: str) -> bool:
        return feature in {"tts_synthesis", "audio_binary_endpoint"}

    async def aclose(self) -> None:
        await self._client.aclose()


def _validated_payload(payload: object) -> dict[str, str | float]:
    if not isinstance(payload, Mapping):
        raise ConnectorError("TTS V1 응답이 JSON object가 아니다.")
    audio_url = payload.get("audio_url")
    duration_sec = payload.get("duration_sec")
    if not isinstance(audio_url, str):
        raise ConnectorError("TTS V1 응답에 audio_url이 없다.")
    if not isinstance(duration_sec, int | float) or duration_sec <= 0:
        raise ConnectorError("TTS V1 응답에 duration_sec가 없다.")
    return {"audio_url": audio_url, "duration_sec": float(duration_sec)}


def _audio_form_data(text: str, voice: str, ref_text: str | None) -> dict[str, str]:
    data = {"text": text, "voice": voice, "language": "korean", "speed": "1.0"}
    if ref_text is not None:
        data["ref_text"] = ref_text
    return data


def _saved_audio_payload(response: httpx.Response, output_dir: Path, voice: str, text: str) -> dict[str, str | float]:
    content_type = response.headers.get("content-type", "audio/wav").split(";")[0]
    if not content_type.startswith("audio/"):
        raise ConnectorError("TTS V1 응답이 오디오 형식이 아니다.")
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / f"{int(time() * 1000)}_{_safe_token(voice)}_{uuid4().hex[:8]}.wav"
    audio_path.write_bytes(response.content)
    return {
        "audio_url": audio_path.resolve().as_uri(),
        "duration_sec": _duration_sec(response, text),
    }


def _duration_sec(response: httpx.Response, text: str) -> float:
    raw_value = response.headers.get("x-duration-sec") or response.headers.get("X-Duration-Sec")
    if raw_value is not None:
        try:
            value = float(raw_value)
            if value > 0:
                return value
        except ValueError:
            pass
    return max(1.0, len(text) / 8.0)


def _media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix == ".m4a":
        return "audio/mp4"
    return "audio/wav"


def _safe_token(value: str) -> str:
    return "".join(char for char in value if char.isalnum() or char in {"-", "_"})[:32] or "voice"
