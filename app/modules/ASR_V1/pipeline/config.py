"""ASR_V1 파이프라인 전체 파라미터 모듈.

os.getenv override 로 런타임에 재조정 가능하도록 한다.
카테고리별 한국어 주석 블록으로 분류.
"""
from __future__ import annotations

import os

# ── VAD(음성 활동 감지) 파라미터 ──────────────────────────────────────────────
VAD_MIN_SILENCE_MS: int = int(os.getenv("ASR_V1_VAD_MIN_SILENCE_MS", "800"))
VAD_SPEECH_PAD_MS: int = int(os.getenv("ASR_V1_VAD_SPEECH_PAD_MS", "200"))
VAD_MIN_SPEECH_MS: int = int(os.getenv("ASR_V1_VAD_MIN_SPEECH_MS", "250"))
VAD_THRESHOLD: float = float(os.getenv("ASR_V1_VAD_THRESHOLD", "0.5"))

# ── 턴 커밋 파라미터 ───────────────────────────────────────────────────────────
# 턴 커밋을 확정하기 위한 최소 전사 글자수
TURN_MIN_CHARS: int = int(os.getenv("ASR_V1_TURN_MIN_CHARS", "2"))
# 마지막 음성 이후 추가 대기 시간(한국어 어미 보호)
TURN_GRACE_MS: int = int(os.getenv("ASR_V1_TURN_GRACE_MS", "300"))

# ── Partial 전사 파라미터 ─────────────────────────────────────────────────────
# 부분 전사 업데이트 주기 (UI 전용, 확정에 영향 없음)
PARTIAL_INTERVAL_MS: int = int(os.getenv("ASR_V1_PARTIAL_INTERVAL_MS", "500"))

# ── 플러시 정책 파라미터 ──────────────────────────────────────────────────────
# 2차 트리거 최소 버퍼 길이
FLUSH_SECONDARY_MIN: int = int(os.getenv("ASR_V1_FLUSH_SECONDARY_MIN", "30"))
# 2차 트리거 쉼표 스캔 범위(끝에서 몇 글자)
FLUSH_SECONDARY_SCAN: int = int(os.getenv("ASR_V1_FLUSH_SECONDARY_SCAN", "10"))

# ── 서버 파라미터 ─────────────────────────────────────────────────────────────
PORT: int = int(os.getenv("ASR_V1_PORT", "8011"))
SAMPLE_RATE: int = int(os.getenv("ASR_V1_SAMPLE_RATE", "16000"))
ASR_MODEL: str = os.getenv("ASR_V1_MODEL", "mlx-qwen3-asr")

# ── 버퍼 하드캡 ───────────────────────────────────────────────────────────────
# 버퍼 최대 누적 시간(초) — 초과 시 자동 커밋
BUFFER_MAX_SEC: float = float(os.getenv("ASR_V1_BUFFER_MAX_SEC", "20.0"))
