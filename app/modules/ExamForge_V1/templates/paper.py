"""실전형 시험지/문항 렌더링 템플릿."""
from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class QuestionFrameSpec:
    """문항별 시험지 표기 계약."""

    template_id: str
    section_title: str
    stem_label: str
    answer_label: str
    answer_space: str
    instruction: str
    scoring_rule: str
    visual_cue: str

    def to_dict(self) -> dict:
        """API 응답용 딕셔너리로 변환한다."""
        return asdict(self)


@dataclass(frozen=True)
class ExamPaperTemplate:
    """시험지 전체 레이아웃 계약."""

    paper_id: str
    display_name: str
    locale: str
    category: str
    subtitle: str
    examinee_fields: tuple[str, ...]
    instructions: tuple[str, ...]
    footer_note: str

    def to_dict(self) -> dict:
        """API 응답용 딕셔너리로 변환한다."""
        return asdict(self)


_KO_STANDARD = ExamPaperTemplate(
    paper_id="ko_standard_mock_exam",
    display_name="한국형 실전 모의고사",
    locale="ko",
    category="korean",
    subtitle="응시자 답안 작성용",
    examinee_fields=("수험번호", "성명", "반/과정", "응시일"),
    instructions=(
        "문제지의 문항 수와 인쇄 상태를 먼저 확인하시오.",
        "객관식은 하나의 정답만 선택하고, 서술형은 지정된 답안란 안에 작성하시오.",
        "문항별 배점을 확인하고 시간 배분을 조절하시오.",
        "학습 자료에 근거해 답하되, 추측성 문장은 감점될 수 있다.",
    ),
    footer_note="끝까지 확인한 뒤 답안 누락 여부를 점검하시오.",
)

_KO_PROFESSIONAL = ExamPaperTemplate(
    paper_id="ko_professional_cert_exam",
    display_name="전문자격 실전 모의고사",
    locale="ko",
    category="professional",
    subtitle="필기/실기 혼합 대비용",
    examinee_fields=("수험번호", "성명", "과목", "교시"),
    instructions=(
        "문제 유형별 지시문을 확인한 뒤 답안을 작성하시오.",
        "필기형은 가장 적절한 하나의 답을 고르시오.",
        "실기형은 요구한 표기 방식과 대소문자, 기호를 정확히 지키시오.",
        "계산·코드 결과 문항은 중간 과정보다 최종 답 표기를 우선한다.",
    ),
    footer_note="실기형 문항은 정답 표기 기준과 부분점수 기준을 함께 확인하시오.",
)

_US_STANDARD = ExamPaperTemplate(
    paper_id="us_standard_mock_exam",
    display_name="US-Style Practice Exam",
    locale="en",
    category="us",
    subtitle="Student response copy",
    examinee_fields=("Student ID", "Name", "Course", "Date"),
    instructions=(
        "Check that all pages and questions are present before starting.",
        "Select one best answer for multiple-choice questions.",
        "Write responses inside the provided answer space.",
        "Use only evidence from the provided study material.",
    ),
    footer_note="Review all responses before submitting.",
)

_DEFAULT_FRAME = QuestionFrameSpec(
    template_id="default",
    section_title="공통 문항",
    stem_label="문제",
    answer_label="답안",
    answer_space="standard-lines",
    instruction="문항에서 요구하는 형식에 맞게 답안을 작성하시오.",
    scoring_rule="정답 정확도와 근거의 적절성을 기준으로 채점한다.",
    visual_cue="generic",
)

_QUESTION_FRAMES: dict[str, QuestionFrameSpec] = {
    "ko_multiple_choice_4": QuestionFrameSpec(
        template_id="ko_multiple_choice_4",
        section_title="객관식 4지선다",
        stem_label="다음 물음에 가장 적절한 답을 고르시오.",
        answer_label="정답 선택",
        answer_space="omr-4",
        instruction="보기 4개 중 정답 1개만 표시하시오.",
        scoring_rule="정답 1개와 선택지 근거가 일치해야 한다.",
        visual_cue="choice",
    ),
    "ko_multiple_choice_5": QuestionFrameSpec(
        template_id="ko_multiple_choice_5",
        section_title="객관식 5지선다",
        stem_label="다음 물음에 가장 적절한 답을 고르시오.",
        answer_label="정답 선택",
        answer_space="omr-5",
        instruction="보기 5개 중 정답 1개만 표시하시오.",
        scoring_rule="정답은 하나이며, 오답은 실제 혼동 포인트를 반영한다.",
        visual_cue="choice",
    ),
    "ko_true_false": QuestionFrameSpec(
        template_id="ko_true_false",
        section_title="OX 판단형",
        stem_label="다음 진술의 참/거짓을 판단하시오.",
        answer_label="O/X 선택",
        answer_space="true-false",
        instruction="참이면 O, 거짓이면 X에 표시하고 핵심 근거를 생각하시오.",
        scoring_rule="명제 판정과 틀린 지점 설명 가능성을 함께 본다.",
        visual_cue="binary",
    ),
    "ko_short_answer": QuestionFrameSpec(
        template_id="ko_short_answer",
        section_title="단답형",
        stem_label="다음 물음에 답하시오.",
        answer_label="단답 답안",
        answer_space="short-line",
        instruction="핵심 용어 또는 한 문장으로 간결하게 답하시오.",
        scoring_rule="핵심 키워드 포함 여부와 의미 정확성을 채점한다.",
        visual_cue="short",
    ),
    "ko_fill_blank": QuestionFrameSpec(
        template_id="ko_fill_blank",
        section_title="빈칸 완성형",
        stem_label="빈칸에 들어갈 알맞은 말을 쓰시오.",
        answer_label="빈칸 답안",
        answer_space="blank-table",
        instruction="빈칸 순서대로 답을 작성하시오.",
        scoring_rule="빈칸별 정답과 허용 표현을 기준으로 채점한다.",
        visual_cue="blank",
    ),
    "ko_ordering": QuestionFrameSpec(
        template_id="ko_ordering",
        section_title="순서배열형",
        stem_label="다음 항목을 올바른 순서로 배열하시오.",
        answer_label="순서 답안",
        answer_space="sequence-slots",
        instruction="항목 기호를 순서대로 적으시오.",
        scoring_rule="전체 순서와 핵심 선후관계가 맞는지 평가한다.",
        visual_cue="ordering",
    ),
    "ko_matching": QuestionFrameSpec(
        template_id="ko_matching",
        section_title="연결형",
        stem_label="좌측 항목과 우측 설명을 올바르게 연결하시오.",
        answer_label="연결 답안",
        answer_space="matching-table",
        instruction="각 좌측 항목에 대응하는 우측 번호를 적으시오.",
        scoring_rule="각 쌍의 1:1 대응 정확도를 기준으로 채점한다.",
        visual_cue="matching",
    ),
    "ko_descriptive": QuestionFrameSpec(
        template_id="ko_descriptive",
        section_title="서술형",
        stem_label="다음 물음에 근거를 포함해 서술하시오.",
        answer_label="서술 답안",
        answer_space="ruled-box",
        instruction="3~6문장으로 핵심 개념, 근거, 결론을 포함하시오.",
        scoring_rule="핵심 키워드, 논리 전개, 부분점수 기준을 함께 적용한다.",
        visual_cue="descriptive",
    ),
    "ko_essay": QuestionFrameSpec(
        template_id="ko_essay",
        section_title="논술형",
        stem_label="다음 논제에 대해 구조화하여 논하시오.",
        answer_label="논술 답안",
        answer_space="essay-sheet",
        instruction="주장, 근거, 예시, 결론의 흐름으로 작성하시오.",
        scoring_rule="논리성, 근거 타당성, 적용력, 표현력을 종합 평가한다.",
        visual_cue="essay",
    ),
    "engineer_written": QuestionFrameSpec(
        template_id="engineer_written",
        section_title="정보처리기사 필기형",
        stem_label="다음 중 가장 적절한 것을 고르시오.",
        answer_label="필기 답안",
        answer_space="omr-5",
        instruction="실제 필기시험처럼 5개 보기 중 하나만 고르시오.",
        scoring_rule="기출식 용어 판별과 오답 소거 능력을 본다.",
        visual_cue="choice",
    ),
    "engineer_practical": QuestionFrameSpec(
        template_id="engineer_practical",
        section_title="정보처리기사 실기형",
        stem_label="다음 요구사항에 맞게 답하시오.",
        answer_label="실기 답안",
        answer_space="practical-box",
        instruction="요구한 표기 방식, 코드 결과, 키워드를 정확히 작성하시오.",
        scoring_rule="정답 표기와 부분점수 기준을 함께 적용한다.",
        visual_cue="practical",
    ),
    "cert_base": QuestionFrameSpec(
        template_id="cert_base",
        section_title="자격시험 기본형",
        stem_label="다음 중 정답을 고르시오.",
        answer_label="정답 선택",
        answer_space="omr-5",
        instruction="시험 범위와 난이도에 맞춰 하나의 답을 선택하시오.",
        scoring_rule="범위 커버리지와 정답 정확성을 기준으로 채점한다.",
        visual_cue="choice",
    ),
    "us_multiple_choice_4": QuestionFrameSpec(
        template_id="us_multiple_choice_4",
        section_title="Multiple Choice",
        stem_label="Choose the best answer.",
        answer_label="Selected answer",
        answer_space="omr-4",
        instruction="Mark exactly one answer from the four choices.",
        scoring_rule="Credit is awarded only when the selected answer matches the key.",
        visual_cue="choice",
    ),
    "us_multiple_choice_5": QuestionFrameSpec(
        template_id="us_multiple_choice_5",
        section_title="Multiple Choice",
        stem_label="Choose the best answer.",
        answer_label="Selected answer",
        answer_space="omr-5",
        instruction="Mark exactly one answer from the five choices.",
        scoring_rule="Distractors should reflect plausible misconceptions.",
        visual_cue="choice",
    ),
    "us_true_false": QuestionFrameSpec(
        template_id="us_true_false",
        section_title="True / False",
        stem_label="Determine whether the statement is true or false.",
        answer_label="T/F selection",
        answer_space="true-false",
        instruction="Mark T for true or F for false.",
        scoring_rule="The judgment must match the statement and its core evidence.",
        visual_cue="binary",
    ),
    "us_short_answer": QuestionFrameSpec(
        template_id="us_short_answer",
        section_title="Short Answer",
        stem_label="Answer the following question.",
        answer_label="Short response",
        answer_space="short-line",
        instruction="Respond with a key term or one concise sentence.",
        scoring_rule="Scoring is based on required keywords and semantic accuracy.",
        visual_cue="short",
    ),
    "us_fill_blank": QuestionFrameSpec(
        template_id="us_fill_blank",
        section_title="Fill in the Blank",
        stem_label="Write the correct term for each blank.",
        answer_label="Blank answers",
        answer_space="blank-table",
        instruction="Write answers in blank order.",
        scoring_rule="Each blank is scored against the answer key and accepted variants.",
        visual_cue="blank",
    ),
    "us_ordering": QuestionFrameSpec(
        template_id="us_ordering",
        section_title="Ordering",
        stem_label="Arrange the items in the correct order.",
        answer_label="Ordered sequence",
        answer_space="sequence-slots",
        instruction="Write the item numbers in order.",
        scoring_rule="Scoring checks the full sequence and key dependencies.",
        visual_cue="ordering",
    ),
    "us_matching": QuestionFrameSpec(
        template_id="us_matching",
        section_title="Matching",
        stem_label="Match each item on the left with the correct item on the right.",
        answer_label="Matching answers",
        answer_space="matching-table",
        instruction="Write the right-side letter for each left-side item.",
        scoring_rule="Each one-to-one pair is scored independently.",
        visual_cue="matching",
    ),
    "us_essay": QuestionFrameSpec(
        template_id="us_essay",
        section_title="Essay",
        stem_label="Write a structured response to the prompt.",
        answer_label="Essay response",
        answer_space="essay-sheet",
        instruction="Include a claim, evidence, example, and conclusion.",
        scoring_rule="Scoring evaluates logic, evidence, application, and clarity.",
        visual_cue="essay",
    ),
}


def question_frame(template_id: str) -> QuestionFrameSpec:
    """template_id에 대응하는 문항 프레임을 반환한다."""
    return _QUESTION_FRAMES.get(template_id, _DEFAULT_FRAME)


def select_paper_template(plan: dict) -> ExamPaperTemplate:
    """시험 계획에 맞는 시험지 전체 템플릿을 선택한다."""
    category = str(plan.get("category", "")).lower()
    locale = str(plan.get("locale", "ko")).lower()
    allocation_ids = {
        str(alloc.get("template_id", ""))
        for alloc in plan.get("type_allocations", [])
        if isinstance(alloc, dict)
    }
    if category == "professional" or any(
        t_id.startswith("engineer_") or t_id.startswith("cert_")
        for t_id in allocation_ids
    ):
        return _KO_PROFESSIONAL
    if locale == "en" or category == "us":
        return _US_STANDARD
    return _KO_STANDARD


def paper_template_contract(template_id: str) -> str:
    """LLM 프롬프트에 넣을 실전 시험지 문항 계약을 만든다."""
    frame = question_frame(template_id)
    if template_id.startswith("us_"):
        # 구역 안내 라벨(section heading)은 시험지 인쇄용일 뿐,
        # 개별 stem 앞에 그대로 복사해 붙이는 접두사가 아님을 명시한다.
        return (
            f"- Exam section: {frame.section_title}\n"
            f"- Section heading (paper layout only, do NOT prepend to any stem): "
            f"{frame.stem_label}\n"
            f"- Answer area: {frame.answer_space} ({frame.answer_label})\n"
            f"- Student instruction: {frame.instruction}\n"
            f"- Scoring rule: {frame.scoring_rule}\n"
            "- Stem rule: write a complete, natural, real-exam-style question. "
            "Vary the phrasing across items and never start every stem with the "
            "same fixed direction sentence."
        )
    # 구역 안내 라벨(stem_label)은 시험지 상단에 한 번 인쇄되는 헤딩이지
    # 각 문항 stem에 반복해서 붙이는 접두사가 아니다. 이 점을 분명히 지시해
    # 모든 stem이 동일 보일러플레이트로 시작하는 현상을 막는다.
    return (
        f"- 시험지 구역: {frame.section_title}\n"
        f"- 구역 안내 라벨(시험지 인쇄용, 개별 stem 앞에 복사 금지): "
        f"{frame.stem_label}\n"
        f"- 답안란: {frame.answer_space} ({frame.answer_label})\n"
        f"- 응시자 지시: {frame.instruction}\n"
        f"- 채점 기준: {frame.scoring_rule}\n"
        "- stem 작성 규칙: 각 문항은 그 자체로 완결된 실전 시험형 발문으로 쓴다. "
        "발문 표현을 문항마다 다양하게 바꾸고, 모든 stem을 동일한 고정 지시 문장으로 "
        "시작하지 않는다."
    )


def paper_template_options() -> list[dict]:
    """사용 가능한 시험지 템플릿 옵션을 반환한다."""
    return [
        _KO_STANDARD.to_dict(),
        _KO_PROFESSIONAL.to_dict(),
        _US_STANDARD.to_dict(),
    ]
