"""문항 메타데이터 보정 유틸리티."""
from __future__ import annotations


def apply_task_metadata(draft: dict, task: dict) -> dict:
    """LLM이 흔드는 난이도/블룸 메타를 생성 청크 계약에 맞춘다.

    template_id 보장 원칙:
    - draft(QuestionDraft.model_dump())의 template_id를 우선 사용한다.
    - draft의 template_id가 빈 문자열이면 task의 template_id로 덮어 써 보충한다.
    - 두 곳 모두 비어 있는 경우는 파이프라인 상류에서 발생해선 안 되므로
      빈 template_id를 그대로 두지 않고 task 값으로 강제 보정한다.
    """
    # task에 difficulty 키가 없을 때 안전한 기본값 3("보통") 사용
    difficulty = int(task.get("difficulty", 3))
    metadata = {
        **draft,
        "difficulty": difficulty,
        "bloom_level": bloom_for_difficulty(difficulty),
    }
    # template_id 보정: draft에서 넘어온 값이 비면 task의 template_id로 채운다.
    # 보충/보수 생성 경로에서 template_id가 유실되는 것을 근본 차단한다.
    if not metadata.get("template_id") and task.get("template_id"):
        metadata["template_id"] = task["template_id"]
    # 슬롯 식별/개념 메타 — 값이 있을 때만 복사
    for key in ("_blueprint_slot", "_chapter", "_concept_key", "_reasoning_type"):
        if task.get(key):
            metadata[key] = task[key]
    # plan-first 계약 필드(num_choices, target_answer_position)는
    # 0/0-index 같은 falsy 값도 의미가 있으므로 None만 제외하고 복사한다.
    # (P1-A 수정: 이 전파가 빠져 있으면 distractors 노드에서 정답위치 정렬이 통째로 스킵됨)
    for key in ("num_choices", "target_answer_position"):
        if task.get(key) is not None:
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
