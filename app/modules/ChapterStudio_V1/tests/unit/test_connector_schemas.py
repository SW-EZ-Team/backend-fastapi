from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIRequest, ChapterAIResponse


def test_request_happy_path() -> None:
    req = ChapterAIRequest(user="안녕", max_tokens=32, temperature=0.2)
    assert req.system == ""
    assert req.extra == {}


def test_request_rejects_empty_user() -> None:
    with pytest.raises(ValidationError):
        ChapterAIRequest(user="", max_tokens=32, temperature=0.2)


def test_request_rejects_bad_temperature() -> None:
    with pytest.raises(ValidationError):
        ChapterAIRequest(user="u", max_tokens=32, temperature=2.1)


def test_request_rejects_bad_max_tokens() -> None:
    with pytest.raises(ValidationError):
        ChapterAIRequest(user="u", max_tokens=0, temperature=0.2)


def test_request_is_frozen() -> None:
    req = ChapterAIRequest(user="u", max_tokens=32, temperature=0.2)
    with pytest.raises(ValidationError):
        setattr(req, "user", "changed")


def test_response_happy_path() -> None:
    resp = ChapterAIResponse(
        text="ok", model="m", input_tokens=1, output_tokens=2, finish_reason="stop"
    )
    assert resp.output_tokens == 2


def test_response_rejects_negative_tokens() -> None:
    with pytest.raises(ValidationError):
        ChapterAIResponse(
            text="ok", model="m", input_tokens=-1, output_tokens=2, finish_reason="stop"
        )


def test_response_is_frozen() -> None:
    resp = ChapterAIResponse(
        text="ok", model="m", input_tokens=1, output_tokens=2, finish_reason="stop"
    )
    with pytest.raises(ValidationError):
        setattr(resp, "text", "changed")
