from __future__ import annotations

from app.modules.ChapterStudio_V1.pipeline.quality_inspection import (
    apply_spelling_fixes,
    inspect_lesson,
    inspect_text,
    strip_cjk,
)


def test_apply_spelling_fixes_rewrites_absolute_value_deterministically() -> None:
    assert apply_spelling_fixes("음수의 절대값이") == "음수의 절댓값이"


def test_strip_cjk_removes_cjk_runs_and_compacts_spacing() -> None:
    cleaned = strip_cjk("가장 最容易한 개념입니다. 특별히 注意하세요.")

    assert cleaned == "가장 한 개념입니다. 특별히 하세요."
    assert "最容易" not in cleaned
    assert "注意" not in cleaned
    assert "  " not in cleaned


def test_strip_cjk_keeps_plain_korean_text() -> None:
    text = "가장 쉬운 개념을 차근차근 설명합니다."

    assert strip_cjk(text) == text


def test_inspect_text_detects_cjk_spelling_and_missing_question_mark() -> None:
    text = "정수的世界里에서 절대값을 비교할 수 있을까요 스스로 질문하며 정리합니다."

    issues = inspect_text(text)
    kinds = {issue.kind for issue in issues}

    assert "cjk" in kinds
    assert "spelling" in kinds
    assert "missing_question_mark" in kinds
    assert any(issue.suggestion == "절댓값" for issue in issues)


def test_inspect_lesson_detects_duplicate_intro_group() -> None:
    repeated = "안녕하세요. 오늘 우리가 왜 하필 이 주제를 배우는지 먼저 생각해 봅시다."
    voice_scripts = [
        f"{repeated} 정수의 기준을 확인합니다.",
        f"{repeated} 분수의 기준을 확인합니다.",
        "이번 화면에서는 바로 예제로 들어가겠습니다. 비교 기준을 손으로 표시합니다.",
    ]

    report = inspect_lesson(voice_scripts, slide_narrations=[])

    assert report.duplicate_intro_groups
    assert report.duplicate_intro_groups[0].members == ["voice_script:0", "voice_script:1"]
    duplicate_buckets = [
        bucket for bucket in report.items if any(issue.kind == "duplicate_intro" for issue in bucket.issues)
    ]
    assert {bucket.index for bucket in duplicate_buckets} == {0, 1}
