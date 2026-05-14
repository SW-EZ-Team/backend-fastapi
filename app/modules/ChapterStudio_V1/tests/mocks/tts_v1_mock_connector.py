from __future__ import annotations

import hashlib


class TTSV1MockConnector:
    name = "tts_v1_mock"

    def __init__(self) -> None:
        self.calls = 0

    async def synthesize(self, text: str, voice: str = "f1") -> dict[str, str | float]:
        self.calls += 1
        digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:8]
        return {"audio_url": f"mock://audio/{digest}", "duration_sec": len(text) * 0.05}

    def supports(self, feature: str) -> bool:
        return feature in {"tts_synthesis"}
