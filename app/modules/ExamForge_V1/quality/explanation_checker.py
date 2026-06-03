"""객관식 해설 품질 검사.

check_explanation_quality: 기존 근거·오답 해설 누락 검사
is_explanation_complete: 미완성(truncation) 탐지 전용 게이트 — validate_node에서 호출

P2-B 정책(오탐 해소):
    truncation은 "문장이 중간에 끊긴" 형태로 나타난다. 따라서 종결성(종결 부호·어미)을
    1차 신호로 본다. 정상 종결 부호로 끝나고 truncation 말미 조사가 아니면, 길이가
    다소 짧아도(예: "정답은 2번이며 ... 모두 제외된다." 53자) 완결로 인정한다.
    하드 길이 플로어는 "거의 빈" 스텁 해설만 걸러내는 매우 낮은 값으로 둔다.
"""
from __future__ import annotations

# 절대 최소 길이 — 이 미만은 사실상 빈 스텁 해설이므로 무조건 미완성으로 본다.
# 정상 짧은 완결 해설("정답은 A입니다." 등)을 오탐하지 않도록 매우 낮게 잡는다.
_EXPLANATION_ABSOLUTE_MIN_CHARS = 6

# 정상 종결 신호 — 이 부호·어미로 끝나면 문장이 완결된 것으로 본다.
_COMPLETE_ENDINGS = (".", "!", "?", "다", "요")

# 해설 미완성 신호 — 이 문자로 끝나면 문장이 끊긴 것으로 간주한다.
# 종결 부호로 끝나더라도 이 말미 조사·어미가 직전에 있으면 truncation으로 판정한다.
_TRUNCATION_ENDINGS = (
    ",",
    "(",
    "[",
    "{",
    " ",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "의",
    "에",
    "과",
    "와",
    "으로",
    "하",
    "되",
    "적",
    "한",
    "이며",
    "하며",
    "이고",
    "하고",
)


def check_explanation_quality(question: dict) -> list[str]:
    """정답 근거와 오답별 오개념 설명이 있는지 확인한다."""
    options = question.get("options") or []
    explanation = str(question.get("explanation", "")).strip()
    if len(options) < 4 or not explanation:
        return []
    issues: list[str] = []
    if "정답" not in explanation and str(question.get("correct_answer", "")) not in explanation:
        issues.append("해설에 정답 근거가 없음")
    missing = [
        str(option.get("label", ""))
        for option in options
        if not option.get("is_correct")
        and not _mentions_option(explanation, str(option.get("label", "")))
    ]
    if missing:
        issues.append(f"오답별 해설 누락: {', '.join(missing)}")
    # 완결성 게이트: 문장이 중간에 끊겼는지 검사(종결성 우선)
    completeness_issues = _check_completeness(explanation)
    issues.extend(completeness_issues)
    return issues


def is_explanation_complete(explanation: str) -> bool:
    """해설 완결성을 결정적으로 검사한다(종결성 우선, 길이 오탐 해소).

    아래 중 하나라도 해당하면 미완성(truncation)으로 간주해 False를 반환한다:
    - 절대 최소 길이(_EXPLANATION_ABSOLUTE_MIN_CHARS) 미만인 빈 스텁
    - 정상 종결 부호·어미로 끝나지 않는 경우(문장 중간 끊김)
    - 종결 부호로 끝나더라도 직전이 truncation 말미 조사인 경우

    정상 종결로 끝나고 말미 조사가 아니면 길이가 짧아도 완결로 본다.
    이 함수는 LLM을 호출하지 않는 순수 함수다.
    """
    text = explanation.strip()
    if not text:
        return False
    return not bool(_check_completeness(text))


def _check_completeness(explanation: str) -> list[str]:
    """해설이 미완성(truncation)인지 결정적으로 검사하고 이슈 목록을 반환한다.

    종결성을 1차 신호로 쓴다 — 정상 종결로 끝나고 말미 조사가 아니면, 길이만으로
    미완성으로 판정하지 않는다(P2-B 오탐 해소). 단 거의 빈 스텁은 길이로 거른다.
    """
    issues: list[str] = []
    # 1) 거의 빈 스텁만 길이로 걸러낸다(정상 짧은 해설은 통과).
    if len(explanation) < _EXPLANATION_ABSOLUTE_MIN_CHARS:
        issues.append(
            f"해설이 {len(explanation)}자로 사실상 비어 truncation 의심 "
            f"(절대 최소 {_EXPLANATION_ABSOLUTE_MIN_CHARS}자)"
        )
        return issues
    # 2) 종결 부호·어미 검사: 완결 신호가 없으면 문장 중간 끊김으로 판단.
    if explanation[-1:] not in _COMPLETE_ENDINGS:
        issues.append("해설이 완결 문장으로 끝나지 않음")
        return issues
    # 3) 정상 종결로 끝나더라도, 종결 부호 직전이 truncation 말미 조사면 끊김으로 본다.
    #    예: "... 비롯된 오개념인데." 의 종결 부호 '.'를 떼고 직전 말미를 검사한다.
    core = explanation.rstrip(".!?").rstrip()
    for ending in _TRUNCATION_ENDINGS:
        if core.endswith(ending):
            issues.append(f"해설 끝이 '{ending}'로 끊겨 truncation 의심")
            break
    return issues


def _mentions_option(explanation: str, label: str) -> bool:
    """해설이 해당 보기 번호/기호를 직접 언급하는지 확인한다."""
    if not label:
        return False
    patterns = (f"{label}번", f"{label}.", f"{label})", f"보기 {label}", f"{label}는")
    return any(pattern in explanation for pattern in patterns)
