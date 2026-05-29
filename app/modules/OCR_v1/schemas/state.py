"""LangGraph OCR 파이프라인 전이 상태 타입 정의.

OCRPipelineState 는 그래프가 Stage 를 이동하면서 누적하는 불변 스냅샷이다.
이 파일은 외부 커넥터·엔진을 일절 import 하지 않는다 (순환 import 방지).
"""
from __future__ import annotations

from typing import TypedDict


class PageClassification(TypedDict):
    """단일 페이지의 PDF 타입 분류 결과."""

    page_num: int           # 1-based 페이지 번호
    page_type: str          # "born-digital" | "scanned" | "mixed"
    has_text_layer: bool    # pdfium2 로 확인한 텍스트 레이어 존재 여부
    image_ratio: float      # 전체 페이지 면적 대비 이미지 비율 (0.0~1.0)
    confidence: float       # 분류 신뢰도 (0.0~1.0)


class PageExtraction(TypedDict):
    """단일 페이지의 OCR 추출 결과."""

    page_num: int           # 1-based 페이지 번호
    markdown: str           # Marker/MinerU 가 생성한 마크다운 텍스트
    tables: list[dict]      # [{md: str, json: dict}] 형식의 표 목록
    formulas: list[str]     # LaTeX 문자열 목록
    engine: str             # 사용된 엔진: "marker" | "mineru"
    llm_corrected: bool     # LLM 사후 교정 여부


class QualityScore(TypedDict):
    """단일 페이지 OCR 품질 점수 집계 결과."""

    page_num: int
    char_corruption: float      # 0.0~1.0 — 낮을수록 오염 없음 (좋음)
    reading_order: float        # 0.0~1.0 — 높을수록 읽기 순서 정상 (좋음)
    table_integrity: float      # 0.0~1.0 — 높을수록 표 구조 온전 (좋음)
    formula_preservation: float # 0.0~1.0 — 높을수록 수식 보존 양호 (좋음)
    overall: float              # 가중 평균 종합 점수
    passed: bool                # quality_pass_threshold 초과 여부


class ChunkRecord(TypedDict):
    """텍스트 청크 단위 — 임베딩 및 벡터 저장소 업서트 단위."""

    chunk_id: str           # 고유 식별자 (파일명+섹션+순서 조합)
    text: str               # 청크 본문 텍스트
    token_count: int        # tiktoken cl100k_base 기준 토큰 수
    section_title: str      # 청크가 속한 섹션 제목
    section_level: int      # 섹션 계층 (1=H1, 2=H2, ...)
    page_nums: list[int]    # 청크가 포함하는 원본 페이지 번호 목록
    tables: list[dict]      # 청크 내 포함된 표 목록
    formulas: list[str]     # 청크 내 포함된 수식 목록


class OCRPipelineState(TypedDict):
    """LangGraph StateGraph 전체 전이 상태.

    각 Stage 가 해당 필드를 채우고 다음 Stage 로 넘긴다.
    bytes 타입의 pdf_bytes 는 엔진 호출 이후 더 이상 변경되지 않는다.

    pipeline_status 값:
        - (없음)   : 아직 시작 전이거나 정상 진행 중
        - "done"    : 전체 파이프라인 정상 완료
        - "partial" : 일부 데이터 손실이 있지만 사용 가능한 결과 반환
        - "error"   : 인프라 오류로 진행 불가 — 하위 노드는 즉시 반환
    """

    # --- 입력 ---
    pdf_bytes: bytes            # 원본 PDF 이진 데이터
    pdf_filename: str           # 원본 파일명 (컬렉션명 자동 생성에 사용)
    total_pages: int            # 전체 페이지 수 (Stage 1 분류 후 확정)

    # --- Stage 1: 페이지 타입 분류 ---
    classifications: list[PageClassification]

    # --- Stage 2+3: OCR 추출 + LLM 교정 ---
    extractions: list[PageExtraction]

    # --- Stage 4: 품질 게이트 ---
    quality_scores: list[QualityScore]
    passed_pages: list[int]     # 품질 통과 페이지 번호 목록
    failed_pages: list[int]     # 품질 미달 페이지 번호 목록

    # --- Stage 5: 폴백 엔진 재추출 ---
    fallback_extractions: list[PageExtraction]

    # --- Stage 6: 후처리 (헤더/푸터 제거, 하이픈 복원 등) ---
    processed_pages: list[PageExtraction]

    # --- Stage 7: 섹션 기반 청킹 ---
    chunks: list[ChunkRecord]

    # --- Stage 8: 임베딩 + 벡터 저장소 업서트 ---
    collection_name: str        # Qdrant 컬렉션명
    embedded_count: int         # 실제 임베딩·저장된 청크 수
    embedding_model: str        # 사용된 임베딩 모델명

    # --- 제어 메타 ---
    current_stage: str          # 현재 실행 중인 Stage 이름
    pipeline_status: str        # (없음) | "done" | "partial" | "error" — 상단 docstring 참조
    error_message: str | None   # 오류 발생 시 메시지 (정상이면 None)
    timings: dict[str, float]   # Stage 별 소요 시간 (초 단위)
