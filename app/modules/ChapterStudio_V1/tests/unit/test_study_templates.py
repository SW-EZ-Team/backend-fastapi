from __future__ import annotations

from app.modules.ChapterStudio_V1.app.study_templates import (
    get_template,
    select_template,
    template_keys,
    template_options,
    visual_contract,
    visual_options,
)


def test_template_catalog_covers_free_topic_domains() -> None:
    keys = set(template_keys())
    required = {
        "chem_reaction", "bio_system", "clinical_reasoning", "algorithm_trace",
        "language_pattern", "history_timeline", "law_policy", "creative_critique",
        "person_profile", "statistics_inference", "research_method", "physics_model",
        "economics_model", "psychology_behavior", "engineering_design", "media_literacy",
        "visual_storyboard", "infographic_summary", "code_visual_walkthrough",
        "reference_navigation", "exam_visual_drill",
    }
    assert required.issubset(keys)
    assert len(keys) >= 45


def test_each_template_has_five_frames_and_five_quiz_slots() -> None:
    for key in template_keys():
        template = get_template(key)
        assert [frame.slide_idx for frame in template.frames] == [0, 1, 2, 3, 4]
        assert len(template.quiz_mix) >= 5
        assert len(template.note_blocks) >= 4


def test_template_options_match_catalog_order() -> None:
    options = template_options()
    assert options[0] == {"value": "auto", "label": "자동 추천"}
    assert options[1] == {"value": "concept_code", "label": "개념 + 코드"}
    assert options[-1] == {"value": "memory_drill", "label": "암기 루틴"}


def test_auto_template_selects_domain_specific_pattern() -> None:
    assert select_template("auto", "화학 반응식과 산화 환원").key == "chem_reaction"
    assert select_template("auto", "영어 관계대명사 문법").key == "language_pattern"
    assert select_template("auto", "통계학자 로널드 피셔").key == "person_profile"
    assert select_template("auto", "회귀분석과 p-value").key == "statistics_inference"
    assert select_template("auto", "양자역학의 관측 문제").key == "physics_model"
    assert select_template("auto", "기후 변화와 탄소 배출").key == "environment_sustainability"
    assert select_template("auto", "교재 p.12 참고도서 다시 읽기").key == "reference_navigation"
    assert select_template("auto", "코드 시각 추적").key == "code_visual_walkthrough"
    assert select_template("auto", "낯선 자유주제").key == "foundation_overview"


def test_visual_contract_exists_for_every_template() -> None:
    visual_keys = {item["value"] for item in visual_options()}
    assert set(template_keys()) == visual_keys
    for key in template_keys():
        contract = visual_contract(key)
        assert "제목/배지" in contract
        assert "목록" in contract
        assert "#" in contract
