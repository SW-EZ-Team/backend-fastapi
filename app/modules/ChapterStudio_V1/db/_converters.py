"""DB row → GenerationContext 변환 유틸리티 — generation_context_loader 전용 원자 모듈.

각 함수는 Row Mapping에서 단일 필드를 꺼내 도메인 타입으로 변환하는 하나의 책임만 가진다.
타입 불일치·유효하지 않은 값은 기본값으로 대체하거나 ConversionError를 발생시킨다.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pydantic import ValidationError

from app.modules.ChapterStudio_V1.app.frontend_contract import DepthLevel, SourceMode, TeacherId
from app.modules.ChapterStudio_V1.app.reference_books.schemas import ReferenceBookContext
from app.modules.ChapterStudio_V1.common.errors import ConversionError


def context_mapping(value: object) -> Mapping[str, object]:
    """JSONB 스냅샷을 Mapping으로 반환한다. 유효하지 않으면 빈 Mapping을 반환한다."""
    if isinstance(value, Mapping):
        return cast(Mapping[str, object], value)
    return {}


def text_field(source: Mapping[str, object], key: str, default: str) -> str:
    """Mapping에서 문자열 필드를 읽는다. 빈 문자열이면 기본값을 반환한다."""
    value = source.get(key)
    if isinstance(value, str) and value != "":
        return value
    return default


def int_field(source: Mapping[str, object], key: str, default: int) -> int:
    """Mapping에서 정수 필드를 읽는다. bool은 int로 취급하지 않는다."""
    value = source.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return default


def bool_field(source: Mapping[str, object], key: str, default: bool) -> bool:
    """Mapping에서 불리언 필드를 읽는다. bool 타입이 아니면 기본값을 반환한다."""
    value = source.get(key)
    if isinstance(value, bool):
        return value
    return default


def source_mode_field(value: object) -> SourceMode:
    """source_type 컬럼값을 SourceMode Literal로 변환한다."""
    if value in ("topic", "pdf"):
        return cast(SourceMode, value)
    raise ConversionError("source_type은 topic 또는 pdf여야 한다.")


def depth_field(value: object) -> DepthLevel:
    """depth 값을 DepthLevel Literal로 변환한다. 미설정이면 normal을 반환한다."""
    if value is None or value == "":
        return "normal"
    if value in ("basic", "normal", "deep"):
        return cast(DepthLevel, value)
    raise ConversionError("depth는 basic, normal, deep 중 하나여야 한다.")


def teacher_field(value: object) -> TeacherId:
    """teacher 값을 TeacherId Literal로 변환한다. 미설정이면 owl을 반환한다."""
    if value is None or value == "":
        return "owl"
    if value in ("owl", "cat", "fox", "bear"):
        return cast(TeacherId, value)
    raise ConversionError("teacher는 owl, cat, fox, bear 중 하나여야 한다.")


def reference_context_field(value: object) -> ReferenceBookContext | None:
    """JSONB 스냅샷에서 ReferenceBookContext를 복원한다. 히트 없으면 None을 반환한다."""
    if not isinstance(value, Mapping):
        return None
    try:
        context = ReferenceBookContext.model_validate(value)
    except ValidationError as exc:
        raise ConversionError(f"reference_book_context 형식 오류: {exc}") from exc
    if not context.has_hits():
        return None
    return context


def table_ref(schema: str, name: str) -> str:
    """schema.table 형식의 정규화된 테이블 참조를 만든다."""
    return f"{schema}.{name}"
