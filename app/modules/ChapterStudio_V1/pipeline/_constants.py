"""ChapterStudio 파이프라인 공통 상수."""
from __future__ import annotations

# converters._difficulty 에서 허용하는 난이도 값 집합
VALID_DIFFICULTY_VALUES: frozenset[str] = frozenset({
    "상", "중", "하",
    "hard", "medium", "easy",
    "기억", "이해", "적용",
    "함정 교정", "실전 판단", "오해",
})
