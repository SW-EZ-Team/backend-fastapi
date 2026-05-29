"""채점 엔진 예외."""


class RubricGradingError(RuntimeError):
    """AI 루브릭 채점 호출이나 응답 계약이 깨졌을 때 사용한다."""


class AnswerKeyIntegrityError(RuntimeError):
    """채점용 정답 키 봉인 검증에 실패했을 때 사용한다."""
