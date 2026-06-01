"""문항 메타데이터 보정 유틸리티."""
from __future__ import annotations


def apply_task_metadata(draft: dict, task: dict) -> dict:
    """LLM이 흔드는 난이도/블룸 메타를 생성 청크 계약에 맞춘다."""
    # task에 difficulty 키가 없을 때 안전한 기본값 3("보통") 사용
    difficulty = int(task.get("difficulty", 3))
    metadata = {
        **draft,
        "difficulty": difficulty,
        "bloom_level": bloom_for_difficulty(difficulty),
    }
    for key in ("_blueprint_slot", "_chapter", "_concept_key", "_reasoning_type"):
        if task.get(key):
            metadata[key] = task[key]
    return metadata


def bloom_for_difficulty(difficulty: int) -> str:
    """난이도에 대응하는 기본 블룸 레벨을 반환한다."""
    return {
        1: "기억",
        2: "이해",
        3: "적용",
        4: "분석",
        5: "평가",
    }.get(difficulty, "이해")
