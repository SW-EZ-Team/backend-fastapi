"""테스트 공통 설정."""
from __future__ import annotations

import pytest

_TEST_ANSWER_KEY_SECRET = "examforge-test-answer-key-secret-32chars-minimum"


@pytest.fixture(autouse=True)
def examforge_answer_key_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    """채점 서명 검증 테스트용 secret을 주입한다."""
    monkeypatch.setenv("EXAMFORGE_ANSWER_KEY_SECRET", _TEST_ANSWER_KEY_SECRET)


@pytest.fixture
def sample_source_text() -> str:
    """테스트용 학습 자료."""
    return """소프트웨어 개발 방법론은 소프트웨어를 체계적으로 개발하기 위한 절차와 방법을 정의한다.
대표적인 방법론으로는 폭포수 모델, 애자일, 스크럼, XP 등이 있다.

폭포수 모델은 요구사항 분석, 설계, 구현, 테스트, 유지보수의 순차적 단계로 진행된다.
각 단계가 완료된 후 다음 단계로 넘어가며, 이전 단계로 돌아가기 어렵다는 특징이 있다.

애자일 방법론은 변화에 유연하게 대응하며 짧은 주기의 반복적 개발을 강조한다.
스크럼은 애자일의 한 형태로 스프린트, 데일리 스크럼, 스프린트 리뷰 등의 이벤트를 포함한다.

XP(eXtreme Programming)는 페어 프로그래밍, TDD, 지속적 통합, 리팩토링 등의 실천법을 강조한다.
코드 품질과 개발자 간 커뮤니케이션을 중시하며 변화를 수용하는 것이 특징이다.

디자인 패턴은 반복적으로 발생하는 설계 문제에 대한 재사용 가능한 해결책이다.
생성 패턴(Singleton, Factory, Builder), 구조 패턴(Adapter, Decorator, Proxy),
행위 패턴(Observer, Strategy, Command) 등으로 분류된다."""


@pytest.fixture
def sample_question_dict() -> dict:
    """테스트용 완성 문제 딕셔너리."""
    return {
        "question_id": "q_test001",
        "draft_id": "draft_test001",
        "template_id": "ko_multiple_choice_5",
        "topic": "소프트웨어 개발 방법론",
        "difficulty": 3,
        "bloom_level": "이해",
        "stem": "다음 중 애자일 방법론의 특징으로 가장 적절한 것은?",
        "options": [
            {"label": "1", "text": "순차적 단계 진행", "is_correct": False},
            {"label": "2", "text": "변화에 유연한 대응", "is_correct": True},
            {"label": "3", "text": "문서 중심 개발", "is_correct": False},
            {"label": "4", "text": "이전 단계 복귀 불가", "is_correct": False},
            {"label": "5", "text": "단일 릴리즈 주기", "is_correct": False},
        ],
        "correct_answer": "2",
        "explanation": "애자일 방법론은 변화에 유연하게 대응하며 짧은 주기의 반복적 개발을 강조한다.",
        "source_reference": "애자일 방법론은 변화에 유연하게 대응",
        "points": 2.0,
    }
