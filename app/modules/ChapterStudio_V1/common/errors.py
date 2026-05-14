from __future__ import annotations


class ChapterStudioError(Exception):
    """ChapterStudio_V1 도메인 공통 예외다."""


class ConversionError(ChapterStudioError):
    """계층 간 데이터 변환 실패를 나타낸다."""


class ValidationFailedError(ChapterStudioError):
    """검증 규칙 위반을 나타낸다."""


class StorageError(ChapterStudioError):
    """저장소 접근 실패를 나타낸다."""
