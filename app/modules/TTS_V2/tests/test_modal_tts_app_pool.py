from __future__ import annotations

import asyncio
import threading
import time

import numpy as np
import pytest

from app.modules.TTS_V2.deploy import modal_tts_app as modal_app


class FakeVoiceCloneModel:
    def __init__(self, index: int, stats: dict[str, object], lock: threading.Lock) -> None:
        self.index = index
        self.stats = stats
        self.lock = lock

    def generate_voice_clone(
        self,
        text: str,
        language: str,
        ref_audio: str,
        ref_text: str | None = None,
        x_vector_only_mode: bool = False,
        speed: float = 1.0,
    ) -> tuple[list[np.ndarray], int]:
        with self.lock:
            used = self.stats["used"]
            assert isinstance(used, list)
            used.append(self.index)
            active = int(self.stats["active"]) + 1
            self.stats["active"] = active
            self.stats["max_active"] = max(int(self.stats["max_active"]), active)
        time.sleep(0.05)
        with self.lock:
            self.stats["active"] = int(self.stats["active"]) - 1
        return [np.zeros(240, dtype=np.float32)], 24000


@pytest.mark.asyncio
async def test_synthesize_acquires_distinct_models_and_releases(monkeypatch: pytest.MonkeyPatch) -> None:
    server = modal_app.Qwen3TTSServer()._synthesize.__self__
    queue: asyncio.Queue[FakeVoiceCloneModel] = asyncio.Queue()
    stats: dict[str, object] = {"used": [], "active": 0, "max_active": 0}
    lock = threading.Lock()
    for index in range(3):
        queue.put_nowait(FakeVoiceCloneModel(index, stats, lock))
    server.model_pool = queue
    server.pool_size = 3
    monkeypatch.setattr(modal_app, "encode_wav", lambda audio, sample_rate: b"RIFFmock")

    await asyncio.gather(
        *[
            server._synthesize(
                text=f"{index}번 합성",
                ref_audio_bytes=b"RIFFref",
                ref_text="레퍼런스",
                language="ko",
                speed=1.0,
            )
            for index in range(3)
        ]
    )

    assert sorted(stats["used"]) == [0, 1, 2]
    assert stats["max_active"] == 3
    assert queue.qsize() == 3


@pytest.mark.asyncio
async def test_synthesize_releases_model_when_generation_fails() -> None:
    class FailingModel:
        def generate_voice_clone(self, **kwargs: object) -> tuple[list[np.ndarray], int]:
            raise RuntimeError("합성 실패")

    server = modal_app.Qwen3TTSServer()._synthesize.__self__
    queue: asyncio.Queue[FailingModel] = asyncio.Queue()
    model = FailingModel()
    queue.put_nowait(model)
    server.model_pool = queue
    server.pool_size = 1

    with pytest.raises(RuntimeError, match="합성 실패"):
        await server._synthesize(
            text="실패 케이스",
            ref_audio_bytes=b"RIFFref",
            ref_text=None,
            language="ko",
            speed=1.0,
        )

    assert queue.qsize() == 1
    assert await queue.get() is model


def test_pool_size_env_clamps_without_import_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BAD_POOL_SIZE", "999")
    assert modal_app._env_int_clamped("BAD_POOL_SIZE", 6, 1, 16) == 16
    monkeypatch.setenv("BAD_POOL_SIZE", "not-number")
    assert modal_app._env_int_clamped("BAD_POOL_SIZE", 6, 1, 16) == 6
