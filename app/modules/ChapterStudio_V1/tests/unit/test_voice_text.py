from __future__ import annotations

from app.modules.ChapterStudio_V1.postprocess.voice_text import apply_selective_tilde


def test_apply_selective_tilde_changes_first_and_last_soft_periods_only() -> None:
    source = "안녕하세요. 오른쪽이 더 커요. 천천히 따라와 보세요."

    result = apply_selective_tilde(source)

    assert result == "안녕하세요~ 오른쪽이 더 커요. 천천히 따라와 보세요~"


def test_apply_selective_tilde_keeps_formal_and_question_sentences() -> None:
    source = "오늘 학습 목표입니다. 준비됐나요? 천천히 볼게요."

    result = apply_selective_tilde(source)

    assert result == "오늘 학습 목표입니다. 준비됐나요? 천천히 볼게요~"


def test_apply_selective_tilde_does_not_duplicate_existing_tilde() -> None:
    source = "같이 해봐~."

    result = apply_selective_tilde(source)

    assert result == "같이 해봐~"
