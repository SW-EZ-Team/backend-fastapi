"""채점 테스트용 실제 스키마 샘플.

기존 choice_question 등은 GradeQuestion을 반환하도록 변경됐다.
Question(생성 경로) 스키마가 아닌 GradeQuestion(채점 경로) 스키마를 사용해야
GradeSubmissionRequest.questions에 바로 넣을 수 있다.
생성 경로 회귀 테스트는 별도 test_grade_question_schema.py에서 수행한다.
"""
from __future__ import annotations

from app.modules.ExamForge_V1.common.ai_bridge import ChapterAIRequest, ChapterAIResponse
from app.modules.ExamForge_V1.schemas.grading import GradeQuestion
from app.modules.ExamForge_V1.schemas.question import MatchingPair, Question, QuestionOption


class RecordingConnector:
    """루브릭 채점 호출 계약을 기록하는 테스트 커넥터."""

    name = "recording_connector"

    def __init__(self) -> None:
        self.requests: list[ChapterAIRequest] = []

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """실제 커넥터 응답 계약과 같은 JSON 문자열을 반환한다."""
        self.requests.append(req)
        return ChapterAIResponse(
            text=(
                '{"score":3.5,"feedback":"핵심 개념은 맞지만 근거가 부족합니다.",'
                '"confidence":0.82,"needs_manual_review":false,'
                '"rubric_breakdown":[{"criterion":"개념 정확성","score":2.0,'
                '"max_score":3.0,"reason":"핵심 용어를 정확히 사용했습니다."},'
                '{"criterion":"근거 제시","score":1.5,"max_score":2.0,'
                '"reason":"근거가 일부 부족합니다."}]}'
            ),
            model="recording-contract",
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
        )

    def supports(self, feature: str) -> bool:
        """테스트 커넥터의 기능 플래그."""
        return feature == "json_mode"


class InconsistentConnector(RecordingConnector):
    """모순된 루브릭 응답을 반환하는 테스트 커넥터."""

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """총점과 세부 점수 합계가 다른 응답을 반환한다."""
        self.requests.append(req)
        return ChapterAIResponse(
            text=(
                '{"score":5.0,"feedback":"모순된 채점입니다.",'
                '"confidence":0.9,"needs_manual_review":false,'
                '"rubric_breakdown":[{"criterion":"개념","score":1.0,'
                '"max_score":5.0,"reason":"총점과 맞지 않습니다."}]}'
            ),
            model="inconsistent-contract",
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
        )


class BooleanScoreConnector(RecordingConnector):
    """숫자 필드에 boolean을 반환하는 테스트 커넥터."""

    async def generate(self, req: ChapterAIRequest) -> ChapterAIResponse:
        """잘못된 숫자 타입 응답을 반환한다."""
        self.requests.append(req)
        return ChapterAIResponse(
            text=(
                '{"score":true,"feedback":"타입이 잘못된 채점입니다.",'
                '"confidence":0.9,"needs_manual_review":false,'
                '"rubric_breakdown":[{"criterion":"개념","score":1.0,'
                '"max_score":5.0,"reason":"score가 boolean입니다."}]}'
            ),
            model="boolean-score-contract",
            input_tokens=0,
            output_tokens=0,
            finish_reason="stop",
        )


def choice_question() -> GradeQuestion:
    """객관식 테스트 문항 — GradeQuestion 반환 (채점 경로 타입)."""
    return GradeQuestion(
        question_id="q-choice",
        draft_id="d-choice",
        template_id="ko_multiple_choice_5",
        topic="개발 방법론",
        difficulty=3,
        bloom_level="이해",
        stem="애자일의 특징은?",
        options=[
            QuestionOption(label="1", text="순차 진행"),
            QuestionOption(label="2", text="변화 대응", is_correct=True),
            QuestionOption(label="3", text="문서 중심"),
        ],
        correct_answer="2",
        explanation="애자일은 변화에 유연하게 대응한다.",
        source_reference="애자일 방법론은 변화에 유연하게 대응",
        points=2.0,
    )


def blank_question() -> GradeQuestion:
    """빈칸 테스트 문항 — GradeQuestion 반환 (채점 경로 타입)."""
    return GradeQuestion(
        question_id="q-blank",
        draft_id="d-blank",
        template_id="ko_fill_blank",
        topic="개발 방법론",
        difficulty=2,
        bloom_level="기억",
        stem="변화 대응 방법론은 ( )이며 대표 프레임워크는 ( )이다.",
        blank_answers=["애자일", "스크럼"],
        correct_answer="애자일, 스크럼",
        explanation="애자일과 스크럼을 구분한다.",
        source_reference="애자일, 스크럼",
        points=2.0,
    )


def ordering_question() -> GradeQuestion:
    """순서형 테스트 문항 — GradeQuestion 반환 (채점 경로 타입)."""
    return GradeQuestion(
        question_id="q-order",
        draft_id="d-order",
        template_id="ko_ordering",
        topic="폭포수 모델",
        difficulty=2,
        bloom_level="이해",
        stem="폭포수 모델 단계를 순서대로 배열하시오.",
        ordering_items=["구현", "요구사항", "설계"],
        correct_ordering=["요구사항", "설계", "구현"],
        correct_answer="요구사항, 설계, 구현",
        explanation="요구사항 이후 설계와 구현이 진행된다.",
        source_reference="요구사항 분석, 설계, 구현",
        points=3.0,
    )


def matching_question() -> GradeQuestion:
    """연결형 테스트 문항 — GradeQuestion 반환 (채점 경로 타입)."""
    return GradeQuestion(
        question_id="q-match",
        draft_id="d-match",
        template_id="ko_matching",
        topic="디자인 패턴",
        difficulty=3,
        bloom_level="이해",
        stem="패턴과 분류를 연결하시오.",
        matching_pairs=[
            MatchingPair(left="Singleton", right="생성 패턴"),
            MatchingPair(left="Adapter", right="구조 패턴"),
        ],
        correct_answer="Singleton-생성 패턴, Adapter-구조 패턴",
        explanation="Singleton은 생성, Adapter는 구조 패턴이다.",
        source_reference="생성 패턴, 구조 패턴",
        points=2.0,
    )


def essay_question() -> GradeQuestion:
    """서술형 테스트 문항 — GradeQuestion 반환 (채점 경로 타입)."""
    return GradeQuestion(
        question_id="q-essay",
        draft_id="d-essay",
        template_id="ko_descriptive",
        topic="애자일",
        difficulty=4,
        bloom_level="분석",
        stem="애자일 방법론이 변화 대응에 유리한 이유를 설명하시오.",
        correct_answer="짧은 반복과 피드백으로 변화에 유연하게 대응한다.",
        explanation="핵심 개념 3점, 근거 제시 2점으로 채점한다.",
        source_reference="짧은 주기의 반복적 개발",
        points=5.0,
    )


def practical_question() -> GradeQuestion:
    """실기형 테스트 문항 — GradeQuestion 반환 (채점 경로 타입)."""
    return GradeQuestion(
        question_id="q-practical",
        draft_id="d-practical",
        template_id="engineer_practical",
        topic="SQL",
        difficulty=3,
        bloom_level="적용",
        stem="두 테이블의 일치 행만 조회하는 조인 키워드를 쓰시오.",
        correct_answer="INNER JOIN | JOIN",
        explanation="표준 조인 키워드 표기를 허용한다.",
        source_reference="SQL JOIN",
        points=4.0,
    )


# ---------------------------------------------------------------------------
# GradeQuestion 기반 샘플 — Spring null 전송 시나리오 재현용
# draft_id·topic·difficulty·bloom_level 을 의도적으로 누락하거나 None으로 설정한다.
# ---------------------------------------------------------------------------


def grade_essay_question_null_meta() -> GradeQuestion:
    """메타 필드 4개가 null인 서술형 채점 문항 — Spring 실제 전송 패턴."""
    return GradeQuestion(
        question_id="q-essay-null",
        # draft_id, topic, difficulty, bloom_level 모두 전달하지 않음 (None)
        template_id="ko_descriptive",
        stem="애자일 방법론이 변화 대응에 유리한 이유를 설명하시오.",
        correct_answer="짧은 반복과 피드백으로 변화에 유연하게 대응한다.",
        explanation="핵심 개념 3점, 근거 제시 2점으로 채점한다.",
        source_reference="짧은 주기의 반복적 개발",
        points=5.0,
    )


def grade_choice_question_null_meta() -> GradeQuestion:
    """메타 필드 4개가 null인 객관식 채점 문항 — Spring 실제 전송 패턴."""
    return GradeQuestion(
        question_id="q-choice-null",
        template_id="ko_multiple_choice_5",
        stem="애자일의 특징은?",
        options=[
            QuestionOption(label="1", text="순차 진행"),
            QuestionOption(label="2", text="변화 대응", is_correct=True),
            QuestionOption(label="3", text="문서 중심"),
        ],
        correct_answer="2",
        explanation="애자일은 변화에 유연하게 대응한다.",
        source_reference="애자일 방법론은 변화에 유연하게 대응",
        points=2.0,
    )
