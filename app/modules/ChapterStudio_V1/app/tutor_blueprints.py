from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TutorBlueprint:
    lens: str
    philosophy: str
    background: str
    mental_model: str
    pitfall: str
    fast_route: str
    transfer_question: str


_PROFILES: dict[str, TutorBlueprint] = {
    "technical": TutorBlueprint("입력·상태·출력·검증", "작동 원리를 작은 재현 단위로 쪼개야 머리에 남는다.", "기술 주제는 도구 이름보다 문제를 자동화하려는 맥락에서 시작한다.", "데이터가 들어오고 상태가 바뀐 뒤 출력이 검증된다.", "문법을 외우고 동작 흐름을 놓치면 금방 잊힌다.", "최소 예제 → 변수 추적 → 실패 사례 → 재사용 기준", "같은 흐름을 다른 입력에 적용하면 어디가 먼저 깨지는가?"),
    "science": TutorBlueprint("현상·원리·증거·한계", "과학 학습은 이름 암기가 아니라 보이는 현상 뒤의 보존·조절 원리를 잡는 일이다.", "관찰 가능한 현상에서 출발해 원인 후보와 증거를 좁힌다.", "구조가 바뀌면 기능이 바뀌고, 조건이 바뀌면 결과가 달라진다.", "공식이나 용어만 외우면 조건과 예외를 놓친다.", "관찰 → 변수 → 원리 → 작은 예측 → 한계", "조건 하나를 바꾸면 결과가 어떻게 달라지는가?"),
    "clinical": TutorBlueprint("증상·위험신호·감별·주의", "의과 학습은 빠른 결론보다 놓치면 위험한 신호를 먼저 분리하는 태도다.", "증상은 병명이 아니라 가능성을 좁히는 단서로 읽는다.", "주호소와 맥락을 놓고 위험도, 가능성, 배제 근거를 순서대로 본다.", "하나의 증상에서 하나의 답을 바로 고르면 위험하다.", "위험 신호 → 감별 후보 → 검사 이유 → 주의 문장", "이 정보가 빠지면 판단이 어떻게 달라지는가?"),
    "quant": TutorBlueprint("변수·분포·추론·한계", "수리·통계 학습은 계산보다 어떤 불확실성을 줄이는지 보는 일이다.", "자료는 현실의 일부만 잘라 온 표본이므로 해석에는 항상 한계가 붙는다.", "변수의 역할, 분포의 모양, 추정의 오차를 분리해서 읽는다.", "상관을 원인처럼 말하거나 p값을 진실처럼 읽기 쉽다.", "변수 정의 → 시각화 → 추정 → 해석 한계 → 반례", "표본이나 가정이 바뀌면 결론은 얼마나 흔들리는가?"),
    "humanities": TutorBlueprint("맥락·관점·근거·비판", "인문·사회 학습은 정답 암기가 아니라 관점이 왜 생겼는지 이해하는 일이다.", "개념은 시대, 제도, 갈등, 언어의 맥락 안에서 의미가 생긴다.", "누가 어떤 문제를 보고 어떤 근거로 주장했는지 따라간다.", "한 관점을 절대화하면 반론과 한계를 보지 못한다.", "맥락 → 주장 → 근거 → 반론 → 오늘의 적용", "다른 관점에서는 같은 사례를 어떻게 해석할까?"),
    "person": TutorBlueprint("시대 문제의식·선택·업적·영향", "인물 학습은 연표 암기가 아니라 그 사람이 어떤 문제를 보고 어떤 선택을 했는지 읽는 일이다.", "인물의 업적은 시대의 질문과 개인의 방법이 만나는 지점에서 나온다.", "시대 배경, 핵심 선택, 방법, 영향, 논쟁을 연결한다.", "업적만 외우면 왜 중요했는지와 한계를 놓친다.", "시대 질문 → 핵심 선택 → 방법 → 영향 → 비판", "이 사람이 없었다면 해당 분야의 질문은 어떻게 달라졌을까?"),
    "language": TutorBlueprint("형태·의미·맥락·오류", "언어 학습은 규칙을 외우는 것보다 언제 그 표현을 쓰는지 감각을 만드는 일이다.", "표현은 문장 안 위치와 상황에 따라 의미와 뉘앙스가 달라진다.", "형태를 보고 의미를 잡고, 실제 문맥에서 오류를 고친다.", "한국어식 직역에 끌리면 자연스러운 사용 맥락을 놓친다.", "패턴 → 예문 → 대조 → 직접 변환 → 오류 수정", "같은 뜻을 더 자연스럽게 말하려면 무엇을 바꿀까?"),
    "exam": TutorBlueprint("출제언어·판별기준·오답루틴", "시험 학습은 많이 읽는 것이 아니라 문제 언어를 기준 언어로 바꾸는 훈련이다.", "출제자는 핵심 기준과 흔한 착각을 선지에 섞어 둔다.", "키워드, 조건, 예외, 오답 유혹을 나눠 읽는다.", "정답만 보면 다음 문항에서 같은 함정에 다시 걸린다.", "출제 표현 → 기준 표시 → 오답 제거 → 회상 루틴", "이 선지가 틀리려면 어떤 조건이 빠져야 하는가?"),
    "foundation": TutorBlueprint("왜 배움·기본관점·작은적용", "낯선 주제는 많은 정보를 넣기 전에 보는 관점을 먼저 잡아야 한다.", "처음에는 범위를 줄이고 핵심 질문을 정해야 학습 부하가 낮아진다.", "정의보다 먼저 문제의식, 핵심 구분, 작은 사례를 만든다.", "처음부터 세부 용어를 많이 넣으면 방향을 잃는다.", "주제의 이유 → 핵심 구분 → 작은 사례 → 자가점검", "오늘 배운 관점으로 새 사례 하나를 설명할 수 있는가?"),
}

_GROUPS: dict[str, tuple[str, ...]] = {
    "technical": ("concept_code", "debug_case", "algorithm_trace", "system_design", "engineering_design", "electronics_signal", "code_visual_walkthrough"),
    "science": ("lab_protocol", "chem_reaction", "bio_system", "physics_model", "astronomy_space", "earth_science", "environment_sustainability", "health_lifestyle"),
    "clinical": ("clinical_reasoning",),
    "quant": ("math_reasoning", "data_analysis", "statistics_inference", "economics_model", "business_strategy", "infographic_summary"),
    "humanities": ("reading_argument", "history_timeline", "humanities_argument", "law_policy", "creative_critique", "writing_structure", "psychology_behavior", "sociology_culture", "geography_region", "media_literacy", "research_method"),
    "person": ("person_profile",),
    "language": ("language_pattern", "vocab_memory"),
    "exam": ("exam_focus", "memory_drill", "exam_visual_drill", "reference_navigation", "visual_storyboard"),
}


def blueprint_for(template_key: str) -> TutorBlueprint:
    """템플릿 key를 실제 과외 설명 전략으로 바꾼다."""
    for profile, keys in _GROUPS.items():
        if template_key in keys:
            return _PROFILES[profile]
    return _PROFILES["foundation"]


def blueprint_contract(template_key: str) -> str:
    """AI 생성 프롬프트에 넣을 과외 기준을 한 줄 계약으로 압축한다."""
    blueprint = blueprint_for(template_key)
    return (
        f"관점={blueprint.lens}; 철학={blueprint.philosophy}; "
        f"배경={blueprint.background}; 빠른학습={blueprint.fast_route}; "
        f"전이질문={blueprint.transfer_question}"
    )
