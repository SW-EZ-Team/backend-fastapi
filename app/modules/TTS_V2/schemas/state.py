"""TTS V2 파이프라인 상태 타입 정의.

AudiobookState 는 LangGraph 그래프가 노드 사이를 이동하며 누적하는 전이 상태다.
ChunkRecord 는 각 텍스트 청크의 처리 결과를 담는 단위 구조다.
이 파일은 numpy 와 typing 이외의 어떤 내부 모듈도 import 하지 않는다 (SRP).
"""
from __future__ import annotations

import numpy as np
from typing import NotRequired, TypedDict


class ChunkRecord(TypedDict):
    """단일 청크의 처리 상태 및 결과 기록.

    chunk_id 형식은 "ch_001" 처럼 3자리 0패딩 인덱스를 사용한다.
    qc_reason 은 QC 통과 여부와 실패 원인을 구분하는 식별자다.
    """

    chunk_id: str
    # 챕터/섹션 위치 정보 — 병합 순서 결정에 사용한다
    chapter_idx: int
    section_title: str

    # 텍스트 처리 단계별 원문 보존 — 디버깅 및 재시도 시 원본 복원에 필요하다
    original_text: str      # 정규화 전 원문
    normalized_text: str    # 클리너 적용 후
    planned_text: str       # LLM 리라이트 후

    # 합성 결과 — None 이면 아직 합성되지 않은 상태다
    audio_np: np.ndarray | None
    sample_rate: int
    duration_sec: float

    # QC 측정값 — None 이면 QC 미실행 상태다
    cer: float | None
    wer: float | None
    qc_passed: bool
    retry_count: int
    # "ok" / "high_cer" / "speed_anomaly" / "repetition" / "excessive_silence"
    qc_reason: str


class AudiobookState(TypedDict):
    """LangGraph StateGraph 의 전체 파이프라인 전이 상태.

    파이프라인의 각 노드는 이 상태를 읽고 필요한 필드만 갱신해 반환한다.
    입력 필드들은 load_input_node 에서 채워지고 이후 노드에서 불변으로 유지된다.
    """

    # 입력 — load_input_node 가 채운다
    input_type: str          # "text" / "markdown" / "file"
    raw_text: str | None
    file_content: str | None  # 파일에서 읽은 텍스트 (input_type == "file" 일 때 사용)
    ref_audio_bytes: bytes
    ref_text: str
    ref_sample_rate: int
    language: str

    # 구조 파싱 결과 — clean_text_node 가 채운다
    # 각 항목 형식: {"title": str, "text": str, "level": int}
    sections: list[dict]

    # 청크 목록 — chunk_text_node 이후 각 노드가 해당 청크를 갱신한다
    chunks: list[ChunkRecord]

    # 파이프라인 제어 플래그
    current_phase: str   # 현재 처리 중인 단계 이름 (로깅 및 재개 복구용)
    max_retries: int
    failed_chunks: list[str]   # QC 최대 재시도 초과 청크 ID — 수동 검토 큐

    # 최종 출력 — merge_node 가 채운다
    merged_audio_bytes: bytes | None
    total_duration_sec: float
    # pipeline_status 값:
    #   - "loading"~"merging" : 각 처리 단계 진행 중
    #   - "done"              : 전체 파이프라인 정상 완료
    #   - "partial"           : 일부 청크 실패, 나머지는 사용 가능
    #   - "error"             : 인프라 오류로 진행 불가 — 하위 노드 즉시 반환
    pipeline_status: str
    error_message: str | None
    timings: dict[str, float]   # 단계별 소요 시간 (ms 단위)

    # 요청별 실행 옵션 — 없으면 config 기본값을 사용한다
    skip_planner: NotRequired[bool]
    skip_postfx: NotRequired[bool]
    qc_engine: NotRequired[str]
    voice_profile_id: NotRequired[str]
    speed: NotRequired[float]
