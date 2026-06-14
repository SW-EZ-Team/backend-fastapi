"""구조화 429 분류 회귀 테스트 (codex 백로그 #6).

google-genai 429 응답의 구조화 필드(status / details[].reason / code)를 우선 보고
billing_exhausted(영구·즉시폴백) vs quota/rate_limit(일시·재시도)를 분리하는지 검증한다.

핵심: status=RESOURCE_EXHAUSTED 는 결제 소진과 분당 quota 초과가 공유하므로,
status 만으로는 영구/일시를 못 가른다. details[].reason 으로 가른다.
문자열 마커는 구조화 필드가 없을 때만 쓰는 이중 안전망(fallback)으로 유지한다.

두 커넥터(루트 ai_connectors, ExamForge 전용)에 일관 적용되는지 함께 검증한다.
실 Gemini 호출 없이 fixture(google APIError payload)만 쓴다.
"""
from __future__ import annotations

from google.genai import errors as genai_errors

from ai_connectors.errors import ConnectorError as RootConnectorError
from ai_connectors.errors import RateLimitError as RootRateLimitError
from ai_connectors.text import gemini_connector as root_gc
from app.modules.ExamForge_V1.common import _connector_gemini_genai as efg
from app.modules.ExamForge_V1.common.errors import ConnectorError as EFGConnectorError
from app.modules.ExamForge_V1.common.errors import RateLimitError as EFGRateLimitError


def _api_error(payload: dict) -> genai_errors.APIError:
    """google-genai APIError(429)를 실제 payload 형태로 생성한다."""
    return genai_errors.ClientError(429, payload)


# ── 실제 google 429 payload fixture ───────────────────────────────────────

# 영구성: 결제 비활성화(reason=BILLING_DISABLED). status는 RESOURCE_EXHAUSTED 공유.
_BILLING_DISABLED_PAYLOAD = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "message": "Your prepayment credits are depleted. Please go to AI Studio "
        "to manage your project and billing.",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "BILLING_DISABLED",
                "domain": "googleapis.com",
            }
        ],
    }
}

# 일시성: 분당 요청 quota 초과(reason=RATE_LIMIT_EXCEEDED). 같은 status.
_RATE_LIMIT_PAYLOAD = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "message": "Quota exceeded for quota metric 'Generate requests per minute'",
        "details": [
            {
                "@type": "type.googleapis.com/google.rpc.ErrorInfo",
                "reason": "RATE_LIMIT_EXCEEDED",
                "domain": "googleapis.com",
            }
        ],
    }
}

# 일시성: reason 없이 status=RESOURCE_EXHAUSTED 만 있고 details 비어 있음
_BARE_RESOURCE_EXHAUSTED_PAYLOAD = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "message": "Resource has been exhausted (e.g. check quota).",
    }
}

# 구조화 필드 부재 + billing 문자열만 → 마커 폴백으로 영구성 판별(이중 안전)
_MSG_ONLY_BILLING_PAYLOAD = {
    "error": {
        "code": 429,
        "message": "Your prepayment credits are depleted. manage your project.",
    }
}

# 함정: details reason은 일시성인데 message에 billing 단어가 섞임.
# 구조화 reason(transient)이 문자열 마커보다 우선해야 한다 → 재시도(일시성).
_TRAP_TRANSIENT_WITH_BILLING_WORD_PAYLOAD = {
    "error": {
        "code": 429,
        "status": "RESOURCE_EXHAUSTED",
        "message": "Quota exceeded — see billing dashboard for limits",
        "details": [{"reason": "RATE_LIMIT_EXCEEDED"}],
    }
}


# ── 루트 ai_connectors 커넥터 ──────────────────────────────────────────────


class TestRootConnectorStructured429:
    def test_billing_disabled_is_permanent_nonretryable(self) -> None:
        """reason=BILLING_DISABLED → 비재시도 ConnectorError(즉시 프로바이더 폴백)."""
        mapped = root_gc._map_api_error(_api_error(_BILLING_DISABLED_PAYLOAD))
        assert not isinstance(mapped, RootRateLimitError)
        assert isinstance(mapped, RootConnectorError)
        assert not isinstance(mapped, root_gc._RETRYABLE_ERRORS)

    def test_rate_limit_reason_is_transient_retryable(self) -> None:
        """reason=RATE_LIMIT_EXCEEDED → RateLimitError(재시도 대상)."""
        mapped = root_gc._map_api_error(_api_error(_RATE_LIMIT_PAYLOAD))
        assert isinstance(mapped, RootRateLimitError)
        assert isinstance(mapped, root_gc._RETRYABLE_ERRORS)

    def test_bare_resource_exhausted_is_transient(self) -> None:
        """details reason 없는 RESOURCE_EXHAUSTED → 일시성(재시도)으로 본다."""
        mapped = root_gc._map_api_error(_api_error(_BARE_RESOURCE_EXHAUSTED_PAYLOAD))
        assert isinstance(mapped, RootRateLimitError)

    def test_message_marker_fallback_when_no_structured_field(self) -> None:
        """구조화 reason 부재 시 message 마커로 billing 판별(이중 안전)."""
        mapped = root_gc._map_api_error(_api_error(_MSG_ONLY_BILLING_PAYLOAD))
        assert not isinstance(mapped, RootRateLimitError)
        assert isinstance(mapped, RootConnectorError)

    def test_structured_reason_wins_over_message_marker(self) -> None:
        """transient reason은 billing 단어가 섞인 message보다 우선 → 재시도."""
        mapped = root_gc._map_api_error(
            _api_error(_TRAP_TRANSIENT_WITH_BILLING_WORD_PAYLOAD)
        )
        assert isinstance(mapped, RootRateLimitError)


# ── ExamForge 전용 커넥터 (일관성) ─────────────────────────────────────────


class TestExamForgeConnectorStructured429:
    def test_billing_disabled_is_permanent_nonretryable(self) -> None:
        mapped = efg._map_api_error(_api_error(_BILLING_DISABLED_PAYLOAD))
        assert not isinstance(mapped, EFGRateLimitError)
        assert isinstance(mapped, EFGConnectorError)
        assert not isinstance(mapped, efg._RETRYABLE_ERRORS)

    def test_rate_limit_reason_is_transient_retryable(self) -> None:
        mapped = efg._map_api_error(_api_error(_RATE_LIMIT_PAYLOAD))
        assert isinstance(mapped, EFGRateLimitError)
        assert isinstance(mapped, efg._RETRYABLE_ERRORS)

    def test_bare_resource_exhausted_is_transient(self) -> None:
        mapped = efg._map_api_error(_api_error(_BARE_RESOURCE_EXHAUSTED_PAYLOAD))
        assert isinstance(mapped, EFGRateLimitError)

    def test_message_marker_fallback_when_no_structured_field(self) -> None:
        mapped = efg._map_api_error(_api_error(_MSG_ONLY_BILLING_PAYLOAD))
        assert not isinstance(mapped, EFGRateLimitError)
        assert isinstance(mapped, EFGConnectorError)

    def test_structured_reason_wins_over_message_marker(self) -> None:
        mapped = efg._map_api_error(
            _api_error(_TRAP_TRANSIENT_WITH_BILLING_WORD_PAYLOAD)
        )
        assert isinstance(mapped, EFGRateLimitError)


# ── reason 추출 헬퍼 단위 검증 (두 커넥터 동일 구현) ────────────────────────


class TestReasonExtraction:
    def test_extracts_reason_from_nested_error_details(self) -> None:
        err = _api_error(_BILLING_DISABLED_PAYLOAD)
        assert "BILLING_DISABLED" in root_gc._iter_error_reasons(err)
        assert "BILLING_DISABLED" in efg._iter_error_reasons(err)

    def test_returns_empty_when_no_details(self) -> None:
        err = _api_error(_MSG_ONLY_BILLING_PAYLOAD)
        assert root_gc._iter_error_reasons(err) == ()
        assert efg._iter_error_reasons(err) == ()

    def test_robust_against_non_dict_details(self) -> None:
        """details가 dict가 아니어도 예외 없이 빈 튜플을 반환한다."""

        class _Weird:
            details = "not a dict"

        assert root_gc._iter_error_reasons(_Weird()) == ()
        assert efg._iter_error_reasons(_Weird()) == ()


def test_both_connectors_share_reason_sets() -> None:
    """두 커넥터가 동일한 billing/transient reason 집합을 쓰는지(일관성) 검증한다."""
    assert root_gc._BILLING_EXHAUSTED_REASONS == efg._BILLING_EXHAUSTED_REASONS
    assert root_gc._TRANSIENT_QUOTA_REASONS == efg._TRANSIENT_QUOTA_REASONS
