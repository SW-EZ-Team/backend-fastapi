"""모의고사 템플릿 계약 카탈로그."""
from __future__ import annotations

from dataclasses import asdict, dataclass

from app.modules.ExamForge_V1.templates.registry import get_template, list_templates
from app.modules.ExamForge_V1.templates.paper import (
    paper_template_contract,
    paper_template_options,
    question_frame,
)


@dataclass(frozen=True)
class ExamTemplateSpec:
    """계획/생성/렌더링이 공유하는 템플릿 계약."""

    template_id: str
    display_name: str
    locale: str
    category: str
    answer_mode: str
    render_layout: str
    student_action: str
    must_have: tuple[str, ...]
    scoring_focus: tuple[str, ...]
    prompt_contract: str
    preview_tags: tuple[str, ...]
    paper_section: str
    paper_instruction: str
    question_frame: str
    answer_frame: str
    scoring_rule: str

    def to_dict(self) -> dict:
        """API 응답용 딕셔너리로 변환한다."""
        return asdict(self)

_SPEC_OVERRIDES: dict[str, dict[str, object]] = {
    "ko_multiple_choice_4": {
        "answer_mode": "single_choice",
        "render_layout": "choice-list",
        "student_action": "보기 4개 중 정답 1개 선택",
        "must_have": ("보기 정확히 4개", "정답 1개", "오답은 실제 혼동 포인트"),
        "scoring_focus": ("개념 구분", "오답 소거", "정답 근거"),
        "prompt_contract": "4개 보기 모두 서로 다른 판단 기준을 가져야 한다.",
        "preview_tags": ("객관식", "빠른 채점", "개념 판별"),
    },
    "ko_multiple_choice_5": {
        "answer_mode": "single_choice",
        "render_layout": "choice-list",
        "student_action": "보기 5개 중 정답 1개 선택",
        "must_have": ("보기 정확히 5개", "정답 1개", "매력적인 오답 4개"),
        "scoring_focus": ("핵심 개념", "함정 회피", "실전 선택지 판별"),
        "prompt_contract": "정답과 오답의 길이 단서가 생기지 않게 균형을 맞춘다.",
        "preview_tags": ("5지선다", "자격시험형", "오답 설계"),
    },
    "ko_short_answer": {
        "answer_mode": "short_text",
        "render_layout": "answer-line",
        "student_action": "핵심 용어 또는 짧은 문장 입력",
        "must_have": ("정답 범위 명확", "동의어 허용 기준", "불필요한 장문 금지"),
        "scoring_focus": ("용어 회상", "정의 정확도", "핵심 키워드"),
        "prompt_contract": "정답은 1~3개 핵심어 또는 한 문장으로 판정 가능해야 한다.",
        "preview_tags": ("단답형", "암기 확인", "키워드 회상"),
    },
    "ko_descriptive": {
        "answer_mode": "rubric_text",
        "render_layout": "rubric-textarea",
        "student_action": "근거를 포함해 3~6문장 서술",
        "must_have": ("채점 루브릭", "핵심 키워드", "부분점수 기준"),
        "scoring_focus": ("논리 전개", "근거 제시", "개념 연결"),
        "prompt_contract": "해설은 채점 포인트와 감점 포인트를 함께 제시한다.",
        "preview_tags": ("서술형", "부분점수", "논리 평가"),
    },
    "ko_essay": {
        "answer_mode": "long_text",
        "render_layout": "essay-panel",
        "student_action": "주장-근거-예시 구조로 긴 답안 작성",
        "must_have": ("논제 명확", "평가 기준", "예시 답안 방향"),
        "scoring_focus": ("구조화", "비판적 사고", "적용력"),
        "prompt_contract": "단순 설명형이 아니라 비교, 평가, 적용 중 하나를 요구한다.",
        "preview_tags": ("논술형", "심화", "구조화 답안"),
    },
    "ko_true_false": {
        "answer_mode": "binary_choice",
        "render_layout": "true-false",
        "student_action": "참/거짓을 고르고 틀린 이유 판단",
        "must_have": ("판정 가능한 명제", "애매한 표현 금지", "오답 이유"),
        "scoring_focus": ("개념 경계", "예외 조건", "문장 판정"),
        "prompt_contract": "항상/절대 같은 단서만으로 풀리지 않게 구성한다.",
        "preview_tags": ("OX형", "빠른 진단", "개념 경계"),
    },
    "ko_fill_blank": {
        "answer_mode": "blank_text",
        "render_layout": "inline-blank",
        "student_action": "문맥 속 빈칸에 핵심어 입력",
        "must_have": ("빈칸 위치 명확", "정답 후보 제한", "문맥 단서 충분"),
        "scoring_focus": ("문맥 이해", "용어 정확도", "개념 연결"),
        "prompt_contract": "빈칸만 봐도 너무 쉽게 맞히는 조사는 피한다.",
        "preview_tags": ("빈칸", "문맥", "용어 적용"),
    },
    "ko_ordering": {
        "answer_mode": "ordered_sequence",
        "render_layout": "step-order",
        "student_action": "단계 카드를 올바른 순서로 배열",
        "must_have": ("순서 항목 3~6개", "단계 간 인과", "정답 순서"),
        "scoring_focus": ("절차 이해", "선후관계", "워크플로우"),
        "prompt_contract": "서로 교환 가능한 항목은 피하고 명확한 전후 관계를 둔다.",
        "preview_tags": ("순서배열", "절차", "단계 흐름"),
    },
    "ko_matching": {
        "answer_mode": "pair_matching",
        "render_layout": "two-column-match",
        "student_action": "좌측 개념과 우측 설명을 연결",
        "must_have": ("쌍 4~6개", "좌우 중복 없음", "유사 개념 혼동 설계"),
        "scoring_focus": ("개념 매핑", "용어-정의 연결", "분류"),
        "prompt_contract": "좌/우 항목은 단순 복붙이 아니라 재표현된 설명이어야 한다.",
        "preview_tags": ("연결형", "매칭", "분류"),
    },
    "engineer_written": {
        "answer_mode": "single_choice",
        "render_layout": "choice-list",
        "student_action": "자격시험 보기 중 최선의 답 선택",
        "must_have": ("출제 포인트", "실전 함정", "기출식 표현"),
        "scoring_focus": ("기출 패턴", "실무 용어", "오답 소거"),
        "prompt_contract": "정보처리기사 필기처럼 짧고 명확한 시험 문체를 유지한다.",
        "preview_tags": ("자격시험", "필기", "기출형"),
    },
    "engineer_practical": {
        "answer_mode": "practical_text",
        "render_layout": "answer-line",
        "student_action": "실기형 키워드 또는 계산 결과 입력",
        "must_have": ("정답 표기 기준", "부분점수", "실무 맥락"),
        "scoring_focus": ("실기 정확도", "표기", "계산/적용"),
        "prompt_contract": "정답 표기 흔들림이 있으면 허용 답안을 함께 제시한다.",
        "preview_tags": ("자격시험", "실기", "표기 기준"),
    },
    "cert_base": {
        "answer_mode": "single_choice",
        "render_layout": "choice-list",
        "student_action": "시험형 보기에서 정답 선택",
        "must_have": ("시험 범위 반영", "합격 기준", "난이도 배분"),
        "scoring_focus": ("범위 커버리지", "난이도", "정확성"),
        "prompt_contract": "실제 자격시험처럼 과목 범위와 난이도를 균형 있게 유지한다.",
        "preview_tags": ("자격시험", "기본형", "범위 점검"),
    },
}


def _default_spec_values(locale: str) -> dict[str, object]:
    """템플릿별 세부 계약이 없을 때 사용할 언어별 기본값."""
    if locale == "en":
        return {
            "answer_mode": "template_defined",
            "render_layout": "generic-card",
            "student_action": "Respond according to the question prompt",
            "must_have": ("Follow the template structure",),
            "scoring_focus": ("Answer accuracy",),
            "prompt_contract": "Preserve the required JSON structure for this template.",
            "preview_tags": ("standard",),
        }
    return {
        "answer_mode": "template_defined",
        "render_layout": "generic-card",
        "student_action": "문항 요구에 맞게 답안 작성",
        "must_have": ("템플릿 구조 준수",),
        "scoring_focus": ("정답 정확도",),
        "prompt_contract": "템플릿 파서가 요구하는 JSON 구조를 정확히 지킨다.",
        "preview_tags": ("기본",),
    }


def get_template_spec(template_id: str) -> ExamTemplateSpec:
    """템플릿 ID에 대응하는 계약을 반환한다."""
    template = get_template(template_id)
    override = {
        **_default_spec_values(template.locale),
        **_SPEC_OVERRIDES.get(template_id, {}),
    }
    frame = question_frame(template_id)
    return ExamTemplateSpec(
        template_id=template.template_id,
        display_name=template.display_name,
        locale=template.locale,
        category=template.category,
        answer_mode=str(override["answer_mode"]),
        render_layout=str(override["render_layout"]),
        student_action=str(override["student_action"]),
        must_have=tuple(override["must_have"]),
        scoring_focus=tuple(override["scoring_focus"]),
        prompt_contract=str(override["prompt_contract"]),
        preview_tags=tuple(override["preview_tags"]),
        paper_section=frame.section_title,
        paper_instruction=frame.instruction,
        question_frame=frame.stem_label,
        answer_frame=frame.answer_space,
        scoring_rule=frame.scoring_rule,
    )

def list_template_specs(
    locale: str | None = None,
    category: str | None = None,
) -> list[ExamTemplateSpec]:
    """필터 조건에 맞는 템플릿 계약 목록을 반환한다."""
    return [
        get_template_spec(t.template_id)
        for t in list_templates(locale=locale, category=category)
    ]

def template_contract(template_id: str) -> str:
    """LLM 프롬프트에 삽입할 단일 템플릿 계약 문자열을 만든다."""
    spec = get_template_spec(template_id)
    must = ", ".join(spec.must_have)
    focus = ", ".join(spec.scoring_focus)
    if spec.locale == "en":
        return (
            f"- template_id: {spec.template_id}\n"
            f"- Display name: {spec.display_name}\n"
            f"- Answer mode: {spec.answer_mode}\n"
            f"- Render layout: {spec.render_layout}\n"
            f"- Student action: {spec.student_action}\n"
            f"- Required conditions: {must}\n"
            f"- Scoring focus: {focus}\n"
            f"- Generation contract: {spec.prompt_contract}\n"
            "[Real exam paper frame]\n"
            f"{paper_template_contract(template_id)}"
        )
    return (
        f"- template_id: {spec.template_id}\n"
        f"- 표시명: {spec.display_name}\n"
        f"- 응답 방식: {spec.answer_mode}\n"
        f"- 렌더링: {spec.render_layout}\n"
        f"- 학생 행동: {spec.student_action}\n"
        f"- 필수 조건: {must}\n"
        f"- 채점 초점: {focus}\n"
        f"- 생성 계약: {spec.prompt_contract}\n"
        "[실전 시험지 틀]\n"
        f"{paper_template_contract(template_id)}"
    )

def allocation_contract(template_ids: list[str]) -> str:
    """시험 계획 노드용 템플릿 배분 계약을 만든다."""
    contracts = [template_contract(t_id) for t_id in template_ids]
    joined = "\n\n".join(contracts)
    return (
        "아래 template_id만 type_allocations에 사용할 수 있다.\n"
        "각 count 합계는 total_questions와 정확히 같아야 한다.\n\n"
        f"{joined}"
    )

def template_options() -> list[dict]:
    """HTML 테스트 페이지에서 사용할 템플릿 옵션 목록을 반환한다."""
    return [spec.to_dict() for spec in list_template_specs()]


def exam_paper_options() -> list[dict]:
    """HTML 테스트 페이지에서 사용할 시험지 틀 목록을 반환한다."""
    return paper_template_options()
