from __future__ import annotations

import pytest

from app.modules.ChapterStudio_V1.app.demo_agent import run_demo_agent
from app.modules.ChapterStudio_V1.app.demo_pipeline import build_demo_result
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.study_templates import select_template
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_for


@pytest.mark.parametrize(
    ("topic", "expected_key", "expected_lens"),
    [
        ("FastAPI 의존성 주입", "concept_code", "입력·상태·출력·검증"),
        ("산화 환원 반응", "chem_reaction", "현상·원리·증거·한계"),
        ("p-value와 신뢰구간", "statistics_inference", "변수·분포·추론·한계"),
        ("로널드 피셔", "person_profile", "시대 문제의식·선택·업적·영향"),
        ("통계학자 로널드 피셔", "person_profile", "시대 문제의식·선택·업적·영향"),
        ("영어 관계대명사", "language_pattern", "형태·의미·맥락·오류"),
        ("관계대명사 who와 which", "language_pattern", "형태·의미·맥락·오류"),
        ("정보처리기사 기출 대비", "exam_focus", "출제언어·판별기준·오답루틴"),
        ("참고도서 페이지 다시 읽기", "reference_navigation", "출제언어·판별기준·오답루틴"),
        ("코드 시각 추적", "code_visual_walkthrough", "입력·상태·출력·검증"),
    ],
)
def test_agent_can_choose_domain_tutoring_blueprint(topic: str, expected_key: str, expected_lens: str) -> None:
    template = select_template("auto", topic)
    assert template.key == expected_key
    assert blueprint_for(template.key).lens == expected_lens


@pytest.mark.asyncio
async def test_voice_script_follows_teacher_tone_and_blueprint() -> None:
    data = DemoGenerationInput(topic="FastAPI 서비스 클래스", teacher="bear", pace=30, tutor_depth=80)
    result = await build_demo_result(data, 5, "concept_code")
    script = result["voice_scripts"][0]["script_text"]
    assert "천천히 반복" in script
    assert "입력·상태·출력·검증" in script
    assert "예외와 한계까지" in script


@pytest.mark.asyncio
async def test_notes_are_tutoring_blocks_not_plain_summary() -> None:
    result = await build_demo_result(DemoGenerationInput(topic="로널드 피셔"), 5, "person_profile")
    bullets = " ".join(item for block in result["note_blocks"] for item in block["bullets"])
    assert "과외 관점:" in bullets
    assert "주의할 함정:" in bullets
    assert "업적만 외우면" in bullets


@pytest.mark.asyncio
async def test_agent_result_exposes_fast_learning_quality_mark() -> None:
    result = await run_demo_agent(DemoGenerationInput(topic="회귀분석과 p-value"), 5, "mock", "auto")
    assert result["template_label"] == "통계 추론"
    assert any(mark.startswith("과외 관점:") for mark in result["quality_marks"])
    assert result["agent_plan"][2]["tool"] == "tutor_blueprint"
