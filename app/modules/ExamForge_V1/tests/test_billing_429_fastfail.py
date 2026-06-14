# 결제성 429(선불 크레딧 소진) 즉시 폴백 회귀 테스트.
# 영구성 429는 RateLimitError(재시도 대상)가 아니라 비재시도 ConnectorError로 매핑돼
# 모델 폴백 루프를 건너뛰고 상위 프로바이더 폴백(OpenAI→Claude)이 즉시 받게 한다.
from app.modules.ExamForge_V1.common import _connector_gemini_genai as efg
from app.modules.ExamForge_V1.common.errors import (
    ConnectorError as EFGConnectorError,
    RateLimitError as EFGRateLimitError,
)


class _FakeErr(Exception):
    def __init__(self, code, msg):
        self.code = code
        super().__init__(msg)


_BILLING_MSG = (
    "429 RESOURCE_EXHAUSTED. Your prepayment credits are depleted. "
    "Please go to AI Studio to manage your project and billing."
)
_TRANSIENT_MSG = "429 Quota exceeded for quota metric requests per minute"


def test_examforge_billing_429_is_nonretryable():
    mapped = efg._map_api_error(_FakeErr(429, _BILLING_MSG))
    assert not isinstance(mapped, EFGRateLimitError)
    assert isinstance(mapped, EFGConnectorError)
    # _RETRYABLE_ERRORS 어디에도 해당하지 않아야 재시도/모델폴백을 건너뛴다
    assert not isinstance(mapped, efg._RETRYABLE_ERRORS)


def test_examforge_transient_429_still_retryable():
    mapped = efg._map_api_error(_FakeErr(429, _TRANSIENT_MSG))
    assert isinstance(mapped, EFGRateLimitError)
    assert isinstance(mapped, efg._RETRYABLE_ERRORS)


def test_global_billing_429_is_nonretryable():
    from ai_connectors.text import gemini_connector as gc
    from ai_connectors.errors import ConnectorError, RateLimitError

    mapped = gc._map_api_error(_FakeErr(429, _BILLING_MSG))
    assert not isinstance(mapped, RateLimitError)
    assert isinstance(mapped, ConnectorError)


def test_global_transient_429_still_retryable():
    from ai_connectors.text import gemini_connector as gc
    from ai_connectors.errors import RateLimitError

    mapped = gc._map_api_error(_FakeErr(429, _TRANSIENT_MSG))
    assert isinstance(mapped, RateLimitError)
