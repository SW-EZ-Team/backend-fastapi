from __future__ import annotations

import pytest

import app.modules.ChapterStudio_V1.common.errors as common_errors
from app.modules.ChapterStudio_V1.ai_connectors.errors import (
    AuthError,
    ConnectorError,
    ContextLengthExceeded,
    ModelNotFoundError,
    RateLimitError,
    TimeoutError,
)


@pytest.mark.parametrize(
    "error_type",
    [RateLimitError, AuthError, ModelNotFoundError, TimeoutError, ContextLengthExceeded],
)
def test_connector_subclasses_are_catchable(error_type: type[ConnectorError]) -> None:
    with pytest.raises(ConnectorError):
        raise error_type("실패")


def test_common_errors_does_not_define_connector_error() -> None:
    assert not hasattr(common_errors, "ConnectorError")


def test_connector_error_is_exception() -> None:
    assert issubclass(ConnectorError, Exception)
