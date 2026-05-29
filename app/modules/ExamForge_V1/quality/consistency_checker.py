"""정답-보기 일관성 검사."""
from __future__ import annotations

# OX/True-False 유형에서 해설 언급 여부 검사를 건너뛸 불리언형 정답 집합
_BOOLEAN_ANSWERS: frozenset[str] = frozenset(
    {"O", "X", "True", "False", "true", "false", "참", "거짓", "T", "F"}
)


def check_consistency(questions: list[dict]) -> list[dict]:
    """각 문제의 정답-보기-해설 일관성을 검사한다.

    Returns:
        불일치 목록: [{"question_id": ..., "issues": [...]}]
    """
    inconsistencies: list[dict] = []

    for q in questions:
        issues: list[str] = []
        q_id = q.get("question_id", "unknown")
        correct_answer = q.get("correct_answer", "")
        options = q.get("options")
        explanation = q.get("explanation", "")

        # 객관식: 정답 번호/레이블이 보기와 일치하는지
        if options:
            correct_labels = [
                o["label"] for o in options if o.get("is_correct")
            ]
            if correct_labels and correct_answer:
                if correct_answer not in correct_labels:
                    issues.append(
                        f"correct_answer '{correct_answer}'가 "
                        f"is_correct 표시된 보기 {correct_labels}와 불일치"
                    )

            # is_correct가 하나도 없는데 correct_answer는 있는 경우
            if not correct_labels and correct_answer:
                issues.append(
                    "correct_answer가 지정됐지만 is_correct=true인 보기가 없음"
                )

            # is_correct가 있는데 correct_answer가 없는 경우
            if correct_labels and not correct_answer:
                issues.append(
                    f"is_correct 표시된 보기 {correct_labels}가 있지만 "
                    "correct_answer 필드가 비어있음"
                )

            # 정답이 보기 중 하나인지
            all_labels = [o["label"] for o in options]
            if correct_answer and correct_answer not in all_labels:
                # 번호가 아닌 텍스트 답인 경우 스킵
                if len(correct_answer) <= 2:
                    issues.append(
                        f"correct_answer '{correct_answer}'가 "
                        f"보기 레이블 {all_labels}에 없음"
                    )

        # 해설이 정답을 언급하는지 (간접 검증)
        # OX/True-False 유형은 불리언형 정답이므로 이 검사에서 제외
        # ("O", "X" 등이 해설에 없더라도 실제 오류가 아님)
        if explanation and correct_answer:
            if correct_answer.strip() not in _BOOLEAN_ANSWERS:
                if len(correct_answer) <= 10:
                    # 짧은 정답은 해설에 포함되어야 함
                    if correct_answer not in explanation:
                        issues.append("해설에 정답이 언급되지 않음")

        if issues:
            inconsistencies.append(
                {"question_id": q_id, "issues": issues}
            )

    return inconsistencies
