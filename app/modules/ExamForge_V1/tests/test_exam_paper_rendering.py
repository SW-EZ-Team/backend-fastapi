"""실전형 시험지 렌더링 템플릿 테스트."""
from __future__ import annotations

from app.modules.ExamForge_V1.pipeline.nodes._html_builder import (
    build_answers_html,
    build_exam_html,
)
from app.modules.ExamForge_V1.templates.paper import (
    paper_template_contract,
    question_frame,
    select_paper_template,
)


def test_selects_professional_paper_for_engineer_allocations() -> None:
    """전문자격 문항 배분은 전문자격 시험지 틀을 선택한다."""
    paper = select_paper_template({
        "locale": "ko",
        "category": "korean",
        "type_allocations": [{"template_id": "engineer_written"}],
    })

    assert paper.paper_id == "ko_professional_cert_exam"
    assert "교시" in paper.examinee_fields


def test_question_frame_contract_is_exam_ready() -> None:
    """문항 프레임 계약이 시험지 지시문과 답안란 정보를 가진다."""
    frame = question_frame("ko_descriptive")
    contract = paper_template_contract("ko_descriptive")

    assert frame.answer_space == "ruled-box"
    assert "서술형" in frame.section_title
    assert "채점 기준" in contract


def test_us_question_frame_contract_uses_english_exam_language() -> None:
    """영문 시험지 프레임은 문항 지시문과 채점 기준까지 영어로 유지한다."""
    frame = question_frame("us_multiple_choice_4")
    contract = paper_template_contract("us_multiple_choice_4")

    assert frame.section_title == "Multiple Choice"
    assert frame.answer_label == "Selected answer"
    assert "Choose the best answer." in frame.stem_label
    assert "Exam section" in contract
    assert "시험지" not in contract
    assert "정답" not in contract


def test_exam_html_renders_realistic_cover_and_answer_sheet() -> None:
    """시험지 HTML에 수험자 정보, 유의사항, 답안 기입란이 포함된다."""
    html = build_exam_html(
        questions=[_choice_question()],
        plan={
            "exam_title": "Rust 실전 모의고사",
            "locale": "ko",
            "category": "korean",
            "total_questions": 1,
            "total_points": 2.0,
            "time_limit_minutes": 30,
            "passing_score": 70.0,
            "type_allocations": [{"template_id": "ko_multiple_choice_5"}],
        },
    )

    assert "수험번호" in html
    assert "응시자 유의사항" in html
    assert "답안 기입란" in html
    assert "① ② ③ ④ ⑤" in html
    assert "보기 5개 중 정답 1개만 표시하시오." in html
    assert "@page{size:A4" in html


def test_us_exam_html_renders_consistent_english_paper() -> None:
    """미국형 시험지는 헤더, 문항, 답안 영역의 고정 문구를 영어로 렌더링한다."""
    html = build_exam_html(
        questions=[{
            "question_id": "q1",
            "draft_id": "d1",
            "template_id": "us_multiple_choice_4",
            "topic": "Ownership",
            "difficulty": 3,
            "bloom_level": "Understanding",
            "stem": "What is the main goal of Rust ownership?",
            "options": [
                {"label": "A", "text": "Memory safety", "is_correct": True},
                {"label": "B", "text": "Dynamic typing", "is_correct": False},
                {"label": "C", "text": "Runtime GC", "is_correct": False},
                {"label": "D", "text": "Global mutable state", "is_correct": False},
            ],
            "correct_answer": "A",
            "explanation": "Ownership prevents invalid memory access.",
            "points": 1.0,
        }],
        plan={
            "exam_title": "Rust Practice Exam",
            "locale": "en",
            "category": "us",
            "total_questions": 1,
            "total_points": 1.0,
            "time_limit_minutes": 30,
            "passing_score": 70.0,
            "type_allocations": [{"template_id": "us_multiple_choice_4"}],
        },
    )

    assert "<html lang='en'>" in html
    assert "Candidate Instructions" in html
    assert "Answer Sheet" in html
    assert "Choose the best answer." in html
    assert "Selected answer" in html
    assert "문항" not in html
    assert "정답" not in html


def test_us_true_false_renders_tf_answer_bubbles() -> None:
    """미국형 참거짓 문항은 계약과 같은 T/F 답안 버블을 렌더링한다."""
    html = build_exam_html(
        questions=[{
            "question_id": "q1",
            "draft_id": "d1",
            "template_id": "us_true_false",
            "topic": "Ownership",
            "difficulty": 2,
            "bloom_level": "Remembering",
            "stem": "Rust ownership is checked at compile time.",
            "correct_answer": "T",
            "explanation": "The compiler checks ownership rules.",
            "points": 1.0,
        }],
        plan={
            "exam_title": "Rust Practice Exam",
            "locale": "en",
            "category": "us",
            "type_allocations": [{"template_id": "us_true_false"}],
        },
    )

    assert "T/F selection" in html
    assert "<span class='bubble'>T</span><span class='bubble'>F</span>" in html
    assert "<span class='bubble'>O</span><span class='bubble'>X</span>" not in html


def test_exam_html_renders_written_question_spaces() -> None:
    """서술형/실기형 문항은 실제 답안지처럼 줄 답안란을 가진다."""
    html = build_exam_html(
        questions=[{
            "question_id": "q1",
            "draft_id": "d1",
            "template_id": "ko_descriptive",
            "topic": "소유권",
            "difficulty": 4,
            "bloom_level": "분석",
            "stem": "Rust 소유권 규칙이 데이터 레이스를 줄이는 과정을 서술하시오.",
            "correct_answer": "모범답안",
            "explanation": "채점 기준",
            "points": 10.0,
        }],
        plan={"exam_title": "서술형 모의고사", "type_allocations": []},
    )

    assert "서술형" in html
    assert "서술 답안" in html
    assert html.count("class='ruled-line'") >= 6


def test_exam_html_renders_matching_and_ordering_frames() -> None:
    """연결형과 순서배열형은 전용 답안 틀을 렌더링한다."""
    html = build_exam_html(
        questions=[
            {
                "template_id": "ko_matching",
                "stem": "용어와 설명을 연결하시오.",
                "difficulty": 3,
                "matching_pairs": [
                    {"left": "소유권", "right": "값의 해제 책임"},
                    {"left": "빌림", "right": "참조를 통한 접근"},
                    {"left": "수명", "right": "참조 유효 범위"},
                ],
                "correct_answer": "1-A, 2-B, 3-C",
                "explanation": "각 개념의 정의에 해당한다.",
            },
            {
                "template_id": "ko_ordering",
                "stem": "컴파일 오류를 해결하는 순서를 배열하시오.",
                "difficulty": 3,
                "ordering_items": ["오류 확인", "소유권 이동 확인", "참조 범위 수정"],
                "correct_answer": "1, 2, 3",
                "explanation": "원인에서 수정으로 이동한다.",
            },
        ],
        plan={"exam_title": "실전 모의고사", "type_allocations": []},
    )

    assert "연결 답안" in html
    assert "좌측 번호별 우측 기호" in html
    assert "순서 답안" in html
    assert "sequence-table" in html


def test_answers_html_contains_answer_key_and_rubric() -> None:
    """답안지 HTML은 정답표와 문항별 채점 기준을 제공한다."""
    html = build_answers_html(
        questions=[_choice_question()],
        plan={
            "exam_title": "Rust 실전 모의고사",
            "type_allocations": [{"template_id": "ko_multiple_choice_5"}],
        },
    )

    assert "정답표" in html
    assert "정답" in html
    assert "채점 기준" in html
    assert "정답은 하나" in html


def _choice_question() -> dict:
    return {
        "question_id": "q1",
        "draft_id": "d1",
        "template_id": "ko_multiple_choice_5",
        "topic": "소유권",
        "difficulty": 3,
        "bloom_level": "이해",
        "stem": "Rust 소유권 규칙의 핵심 목적은 무엇인가?",
        "options": [
            {"label": "1", "text": "메모리 안전성 확보", "is_correct": True},
            {"label": "2", "text": "동적 타입 변환", "is_correct": False},
            {"label": "3", "text": "런타임 GC 강제", "is_correct": False},
            {"label": "4", "text": "전역 상태 공유", "is_correct": False},
            {"label": "5", "text": "컴파일 생략", "is_correct": False},
        ],
        "correct_answer": "1",
        "explanation": "소유권은 컴파일 타임에 메모리 안전성을 보장한다.",
        "source_reference": "소유권 규칙",
        "points": 2.0,
    }
