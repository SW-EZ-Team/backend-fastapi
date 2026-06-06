from __future__ import annotations


def personalization_contract(
    *,
    weak_points: str,
    audience_level: str,
    tone: int,
    pace: int,
    tutor_depth: int,
    socratic: int,
    learning_goal: str,
    use_formal_speech: bool = True,
    use_emoji: bool = False,
    tutor_name: str = "",
    tutor_tagline: str = "",
    component_rule: str = "",
    weak_component_rule: str = "",
) -> str:
    """프롬프트에 넣을 개인화 계약을 한곳에서 만든다."""
    level = audience_level.strip() or "일반 학습자"
    goal = learning_goal.strip() or "핵심 개념 이해와 실습"
    lines = [
        "개인화 계약:",
        f"학습자 수준 {level}에 맞춰 난이도·용어·예시 조정. 학습 목표 {goal}.",
        _tutor_control_line(tone, pace, tutor_depth, socratic),
        _speech_line(use_formal_speech),
        _emoji_line(use_emoji),
    ]
    persona_line = _persona_line(tutor_name, tutor_tagline)
    if persona_line:
        lines.append(persona_line)
    weak_line = _weak_points_line(weak_points)
    if weak_line:
        lines.append(weak_line)
        if weak_component_rule:
            lines.append(weak_component_rule)
    if component_rule:
        lines.append(component_rule)
    return "\n".join(lines)


def _tutor_control_line(tone: int, pace: int, tutor_depth: int, socratic: int) -> str:
    return (
        f"말투는 {_tone_label(tone)}로 유지하고, 설명 속도는 {_pace_label(pace)}로 조절한다. "
        f"튜터 깊이는 {_depth_label(tutor_depth)}로 맞추며, 질문 스타일은 {_socratic_label(socratic)}로 둔다."
    )


def _weak_points_line(weak_points: str) -> str:
    cleaned = weak_points.strip()
    if not cleaned:
        return ""
    return f"학습자 약점 개념: {cleaned} — 이 개념들을 집중 보강·반복 노출하고 흔한 오개념을 교정한다."


def _speech_line(use_formal_speech: bool) -> str:
    # ~봐요/~봐 어미 예시는 narration·음성대본 전용임을 명시한다.
    # 퀴즈 발문(question 필드)은 이 말투 지시를 따르지 않고
    # parallel_prompt_text.py의 question 발문 형식 규칙을 따른다.
    if use_formal_speech:
        return (
            "말투(narration·음성대본 한정): 존댓말로 한다(~해요,~예요,~습니다). "
            "다정하고 또렷한 과외쌤 톤. "
            "단, 이 말투 규칙은 설명·narration에만 적용한다 — 퀴즈 발문은 별도 형식 규칙을 따른다."
        )
    return (
        "말투(narration·음성대본 한정): 반말체로 한다(~해,~야,~거야). "
        "친근한 또래 과외쌤 톤. 과한 ㅋㅋ·은어 금지. "
        "단, 이 말투 규칙은 설명·narration에만 적용한다 — 퀴즈 발문은 별도 형식 규칙을 따른다."
    )


def _emoji_line(use_emoji: bool) -> str:
    if use_emoji:
        return "narration/음성대본에 가벼운 이모지 문장당 최대1개."
    return "이모지 금지."


def _persona_line(tutor_name: str, tutor_tagline: str) -> str:
    name = tutor_name.strip()
    tagline = tutor_tagline.strip()
    if not name and not tagline:
        return ""
    if name and tagline:
        return f"튜터 페르소나: {name} — {tagline}. 일관된 말투 유지."
    return f"튜터 페르소나: {name or tagline}. 일관된 말투 유지."


def _tone_label(value: int) -> str:
    score = _clamp(value)
    if score <= 33:
        return "차분하고 간결한 말투"
    if score <= 66:
        return "친절하고 균형 잡힌 과외 말투"
    return "격려가 많고 부드러운 과외 말투"


def _pace_label(value: int) -> str:
    score = _clamp(value)
    if score <= 33:
        return "천천히, 단계 사이 복습을 넣는 방식"
    if score <= 66:
        return "보통 속도로 핵심과 예시를 균형 있게 설명하는 방식"
    return "빠르게 핵심을 압축하되 약점 부분은 놓치지 않는 방식"


def _depth_label(value: int) -> str:
    score = _clamp(value)
    if score <= 33:
        return "기초 용어와 직관을 먼저 세우는 수준"
    if score <= 66:
        return "원리와 적용 예시를 함께 다루는 수준"
    return "원리, 예외, 실전 함정까지 짚는 심화 수준"


def _socratic_label(value: int) -> str:
    score = _clamp(value)
    if score <= 33:
        return "직접 설명 중심, 확인 질문은 최소화"
    if score <= 66:
        return "중간중간 짧은 자가점검 질문 포함"
    return "소크라테스식 질문과 오개념 점검을 자주 포함"


def _clamp(value: int) -> int:
    if value < 0:
        return 0
    if value > 100:
        return 100
    return value


__all__ = ["personalization_contract"]
