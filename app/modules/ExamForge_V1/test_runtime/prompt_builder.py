"""Gemini CLI 실전 모의고사 프롬프트 생성기."""
from __future__ import annotations

import json


def build_exam_json_prompt(
    *,
    source_text: str,
    subject: str,
    total_questions: int,
    locale: str = "ko",
    template_id: str = "ko_multiple_choice_5",
) -> str:
    """ExamForge 렌더러가 그대로 소비할 JSON 생성 요청을 만든다."""
    schema = {
        "exam_plan": {
            "exam_title": f"{subject} 실전 모의고사",
            "subject": subject,
            "total_questions": total_questions,
            "total_points": float(total_questions * 2),
            "time_limit_minutes": max(10, total_questions * 3),
            "locale": locale,
            "category": "korean" if locale == "ko" else "us",
            "type_allocations": [{
                "template_id": template_id,
                "count": total_questions,
                "difficulty_distribution": {"3": total_questions},
                "points_per_question": 2.0,
            }],
            "topic_weights": {"핵심 개념": 1.0},
            "passing_score": 60.0,
            "bloom_distribution": {"이해": 0.4, "적용": 0.4, "분석": 0.2},
        },
        "questions": [{
            "question_id": "q1",
            "draft_id": "d1",
            "template_id": template_id,
            "topic": "핵심 개념",
            "difficulty": 3,
            "bloom_level": "이해",
            "stem": "문제 줄기",
            "options": [
                {"label": "1", "text": "선택지", "is_correct": True}
            ],
            "correct_answer": "1",
            "explanation": "자료에 근거한 해설",
            "source_reference": "자료 근거",
            "points": 2.0,
        }],
    }
    return (
        "도구를 사용하지 마세요. 파일을 읽거나 수정하지 마세요.\n"
        "아래 자료만 근거로 실제 시험처럼 문항을 생성하세요.\n"
        "반드시 JSON 객체 하나만 출력하세요. Markdown 코드블록은 쓰지 마세요.\n"
        "응답 구조는 아래 예시와 같은 키를 유지하세요.\n\n"
        f"[출력 JSON 예시]\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n\n"
        f"[과목]\n{subject}\n\n"
        f"[문항 수]\n{total_questions}\n\n"
        f"[자료]\n{source_text[:12000]}"
    )


def sample_source_text() -> str:
    """라이브 스모크용 짧은 샘플 자료를 반환한다."""
    return (
        "Rust의 소유권 시스템은 메모리 안전성을 컴파일 타임에 보장한다. "
        "값은 하나의 소유자를 가지며, 소유자가 스코프를 벗어나면 값은 해제된다. "
        "빌림은 참조를 통해 값에 접근하는 방식이며, 불변 참조는 여러 개 가능하지만 "
        "가변 참조는 동시에 하나만 허용된다. 수명은 참조가 유효한 범위를 설명하며, "
        "컴파일러는 dangling reference를 막기 위해 수명 규칙을 검사한다. "
        "move가 발생하면 이전 바인딩은 더 이상 사용할 수 없고, Copy 타입은 예외적으로 복사된다."
    )
