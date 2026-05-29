"""TTS V2 API 응답 Pydantic 모델 정의.

TTSV2Response 는 파이프라인 실행 결과를 클라이언트에 전달하는 직렬화 구조체다.
audio_base64 는 WAV 포맷 바이너리를 base64로 인코딩한 문자열이다.
이 파일은 pydantic 이외의 내부 모듈을 import 하지 않는다 (SRP).
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class TTSV2Response(BaseModel):
    """TTS V2 파이프라인 응답 모델.

    failed_chunk_ids 가 비어 있으면 전체 청크 QC를 통과한 것이다.
    avg_cer / avg_wer 는 QC를 건너뛴 경우 None 이 된다.
    timings 는 각 파이프라인 단계 이름을 키, 소요 ms를 값으로 담는다.
    """

    # base64 인코딩된 WAV 바이너리 — 클라이언트가 직접 재생할 수 있다
    audio_base64: str
    total_duration_sec: float
    # 합성 샘플링 레이트 — qwen3-tts-1.7b 기본값 24000 Hz
    sample_rate: int = Field(default=24000)
    chunk_count: int
    failed_chunk_count: int
    # QC 최대 재시도 초과로 수동 검토 큐에 남은 청크 ID 목록
    failed_chunk_ids: list[str]
    # QC 엔진이 없거나 skip_postfx 일 때는 None 이 된다
    avg_cer: float | None
    avg_wer: float | None
    # QC 사유별 청크 수 — 반복/환각/고CER 원인 확인용
    qc_reason_counts: dict[str, int] = Field(default_factory=dict)
    # 청크별 QC 사유 — 프론트 디버깅/운영 리포트에 사용
    chunk_qc_reasons: list[dict[str, str]] = Field(default_factory=list)
    # 단계별 소요 ms — "loading", "cleaning", "planning", ... 키를 사용한다
    timings: dict[str, float]
    model: str = Field(default="qwen3-tts-1.7b-base")
    # 실제 QC에 사용된 엔진 — "whisperx" / "v1_asr" / "both" / "none"
    qc_engine_used: str
