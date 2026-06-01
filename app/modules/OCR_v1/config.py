"""OCR_v1 설정값 — 환경변수로 모든 값을 override 가능하다.

이 파일은 os 만 import 한다 (순환 import 방지).
모든 함수는 호출 시마다 환경변수를 다시 읽어 동적 변경을 지원한다.
"""
from __future__ import annotations

import os


def primary_engine() -> str:
    """기본 OCR 엔진 (env: OCR_V1_PRIMARY_ENGINE)."""
    return os.environ.get("OCR_V1_PRIMARY_ENGINE", "marker")


def fallback_engine() -> str:
    """품질 실패 시 사용할 폴백 OCR 엔진 (env: OCR_V1_FALLBACK_ENGINE)."""
    return os.environ.get("OCR_V1_FALLBACK_ENGINE", "mineru")


def marker_timeout_sec() -> int:
    """Marker 엔진 단일 호출 타임아웃 (초, env: OCR_V1_MARKER_TIMEOUT_SEC)."""
    return int(os.environ.get("OCR_V1_MARKER_TIMEOUT_SEC", "300"))


def marker_batch_multiplier() -> int:
    """Marker 배치 크기 배율 (env: OCR_V1_MARKER_BATCH_MULTIPLIER)."""
    return int(os.environ.get("OCR_V1_MARKER_BATCH_MULTIPLIER", "2"))


def marker_use_llm_model() -> str:
    """Marker LLM 교정에 사용할 모델명 (비면 LLM 교정 비활성, env: OCR_V1_MARKER_USE_LLM_MODEL)."""
    return os.environ.get("OCR_V1_MARKER_USE_LLM_MODEL", "")


def quality_pass_threshold() -> float:
    """품질 종합 점수 통과 최소 임계값 (env: OCR_V1_QUALITY_PASS_THRESHOLD)."""
    return float(os.environ.get("OCR_V1_QUALITY_PASS_THRESHOLD", "0.7"))


def char_corruption_max() -> float:
    """허용 최대 문자 오염률 — 초과 시 품질 실패 (env: OCR_V1_CHAR_CORRUPTION_MAX)."""
    return float(os.environ.get("OCR_V1_CHAR_CORRUPTION_MAX", "0.05"))


def table_integrity_min() -> float:
    """표 무결성 최소 점수 임계값 (env: OCR_V1_TABLE_INTEGRITY_MIN)."""
    return float(os.environ.get("OCR_V1_TABLE_INTEGRITY_MIN", "0.8"))


def formula_preservation_min() -> float:
    """수식 보존 최소 점수 임계값 (env: OCR_V1_FORMULA_PRESERVATION_MIN)."""
    return float(os.environ.get("OCR_V1_FORMULA_PRESERVATION_MIN", "0.9"))


def reading_order_min() -> float:
    """읽기 순서 최소 점수 임계값 (env: OCR_V1_READING_ORDER_MIN)."""
    return float(os.environ.get("OCR_V1_READING_ORDER_MIN", "0.85"))


def chunk_min_tokens() -> int:
    """섹션 청크 최소 토큰 수 — 미달 시 다음 섹션과 병합 (env: OCR_V1_CHUNK_MIN_TOKENS)."""
    return int(os.environ.get("OCR_V1_CHUNK_MIN_TOKENS", "600"))


def chunk_max_tokens() -> int:
    """섹션 청크 최대 토큰 수 — 초과 시 단락 경계에서 분할 (env: OCR_V1_CHUNK_MAX_TOKENS)."""
    return int(os.environ.get("OCR_V1_CHUNK_MAX_TOKENS", "1200"))


def embedding_model() -> str:
    """사용할 dense+sparse 임베딩 모델 (env: OCR_V1_EMBEDDING_MODEL)."""
    return os.environ.get("OCR_V1_EMBEDDING_MODEL", "BAAI/bge-m3")


def embedding_batch_size() -> int:
    """임베딩 배치 크기 (env: OCR_V1_EMBEDDING_BATCH_SIZE)."""
    return int(os.environ.get("OCR_V1_EMBEDDING_BATCH_SIZE", "32"))


def qdrant_url() -> str:
    """Qdrant 서버 URL (env: OCR_V1_QDRANT_URL)."""
    return os.environ.get("OCR_V1_QDRANT_URL", "http://localhost:6333")


def qdrant_api_key() -> str | None:
    """Qdrant 인증 키 (env: QDRANT_API_KEY 또는 OCR_V1_QDRANT_API_KEY). 미설정이면 None — 인증 없는 Qdrant/인메모리에서 정상."""
    key = os.environ.get("OCR_V1_QDRANT_API_KEY") or os.environ.get("QDRANT_API_KEY")
    return key or None


def qdrant_collection() -> str:
    """기본 Qdrant 컬렉션명 (env: OCR_V1_QDRANT_COLLECTION)."""
    return os.environ.get("OCR_V1_QDRANT_COLLECTION", "ocr_v1_chunks")


def reranker_model() -> str:
    """크로스인코더 리랭킹 모델 (env: OCR_V1_RERANKER_MODEL)."""
    return os.environ.get("OCR_V1_RERANKER_MODEL", "BAAI/bge-reranker-v2-m3")


def rerank_top_k() -> int:
    """리랭킹 전 초기 검색 결과 수 (env: OCR_V1_RERANK_TOP_K)."""
    return int(os.environ.get("OCR_V1_RERANK_TOP_K", "10"))


def server_port() -> int:
    """FastAPI 서버 바인딩 포트 (env: OCR_V1_PORT)."""
    return int(os.environ.get("OCR_V1_PORT", "8005"))


def max_quality_retries() -> int:
    """품질 실패 페이지에 대한 폴백 최대 재시도 횟수 (env: OCR_V1_MAX_QUALITY_RETRIES)."""
    return int(os.environ.get("OCR_V1_MAX_QUALITY_RETRIES", "1"))
