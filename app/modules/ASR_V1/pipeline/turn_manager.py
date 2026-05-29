"""턴 커밋 정책 모듈.

VAD 상태 변화를 추적하고 턴 커밋 조건이 충족되면 commit=True를 반환한다.
한국어 어미 보호를 위해 grace_ms 추가 대기 시간을 적용한다.
"""
from __future__ import annotations

from typing import TypedDict

from app.modules.ASR_V1.pipeline.config import TURN_GRACE_MS, TURN_MIN_CHARS, VAD_MIN_SILENCE_MS


class TurnDecision(TypedDict):
    """턴 커밋 판단 결과."""

    commit: bool
    reason: str
    silence_duration_ms: float


class TurnManager:
    """음성/침묵 전이를 추적해 턴 커밋 시점을 결정한다.

    falling edge(speech→silence) 감지 시 침묵 타이머를 시작하고,
    충분한 침묵 + 최소 글자수 조건이 충족되면 커밋을 신호한다.
    """

    def __init__(
        self,
        min_silence_ms: int = VAD_MIN_SILENCE_MS,
        turn_min_chars: int = TURN_MIN_CHARS,
        grace_ms: int = TURN_GRACE_MS,
    ) -> None:
        """초기 상태 설정."""
        self._min_silence_ms = min_silence_ms
        self._turn_min_chars = turn_min_chars
        self._grace_ms = grace_ms
        self._was_speaking: bool = False
        self._silence_start_ms: float | None = None
        self._grace_elapsed_ms: float = 0.0

    def update(
        self,
        is_speech: bool,
        timestamp_ms: float,
        partial_text: str,
    ) -> TurnDecision:
        """VAD 상태와 타임스탬프로 턴 커밋 여부를 결정한다.

        Args:
            is_speech: 현재 프레임이 음성인지 여부
            timestamp_ms: 현재 프레임의 타임스탬프 (ms)
            partial_text: 현재까지 부분 전사 텍스트
        """
        silence_ms = 0.0

        if self._was_speaking and not is_speech:
            # falling edge — 침묵 타이머 시작
            self._silence_start_ms = timestamp_ms
            self._grace_elapsed_ms = 0.0

        if not is_speech and self._silence_start_ms is not None:
            silence_ms = timestamp_ms - self._silence_start_ms

            # grace 구간 누적
            if silence_ms >= self._min_silence_ms:
                self._grace_elapsed_ms = silence_ms - self._min_silence_ms

            # 최소 침묵 + 최소 글자수 + grace 경과 시 커밋
            enough_silence = silence_ms >= self._min_silence_ms + self._grace_ms
            enough_chars = len(partial_text.strip()) >= self._turn_min_chars
            if enough_silence and enough_chars:
                self._was_speaking = False
                self._silence_start_ms = None
                return TurnDecision(
                    commit=True,
                    reason="silence_threshold",
                    silence_duration_ms=silence_ms,
                )

        self._was_speaking = is_speech
        return TurnDecision(commit=False, reason="", silence_duration_ms=silence_ms)

    def reset(self) -> None:
        """커밋 후 상태 초기화."""
        self._was_speaking = False
        self._silence_start_ms = None
        self._grace_elapsed_ms = 0.0
