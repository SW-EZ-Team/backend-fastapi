from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from app.modules.ChapterStudio_V1.ai_connectors.schemas import ChapterAIResponse
import app.modules.ChapterStudio_V1.scripts.run_modal_actual_lesson_eval as actual_eval
from app.modules.ChapterStudio_V1.scripts.run_modal_actual_lesson_eval import (
    LessonPayload,
    _has_tts_delivery_style,
    _extract_json_object,
    _expand_voice_scripts,
    _merge_voice_segments,
    _parse_single_voice_segment,
    _parse_single_voice_script,
    _parse_payload,
    _score_ops,
    _score_scale_contract,
    _supporting_repair_system,
    _system_prompt,
    _slide_sentence_ok,
    _tts_sentence_count,
    _user_prompt,
    _validate_payload_replay_args,
    _voice_full_rewrite_user,
    _voice_expansion_system,
    _voice_segment_system,
    _voice_script_needs_retry,
)


def test_actual_lesson_prompt_pins_strict_json_keys() -> None:
    system = _system_prompt(12)
    user = _user_prompt(12, learner_profile="학습자", weak_points="혼동행렬, 과대적합", reference_context_prompt="")

    assert "slides[i] 키는 정확히 slide_idx, title, focus, checkpoint, category, html, css" in system
    assert "category 값은 text, diagram, code, math, chart, interactive, table" in system
    assert "표가 주 시각자료인 슬라이드는 category를 table" in system
    assert "4는 formula math" in system
    assert "slide_idx 6~11은 category가 아니라 html 안에" in system
    assert "category 값에 metric-card" in system
    assert "options, answer, correct 같은 대체 키를 쓰지 않는다" in system
    assert "Easy/Medium/Hard 금지" in system
    assert "bullet 본문마다 p.번호" in system
    assert "note_blocks는 정확히 4개" in system
    assert "모든 voice_scripts[i].script_text에 p.7처럼" in system
    assert "정답 이유와 오답 함정" in system
    assert "voice_scripts는 객체 배열" in user
    assert "difficulty는 Easy/Medium/Hard가 아니라" in user
    assert "한국어 200~360자" in user
    assert "slide_idx 5 category=interactive" in user
    assert "10 category=interactive 및 HTML에는 step-grid" in user
    assert "script_text는 슬라이드마다 8~12문장" in user
    assert "button만 나열하면 실패" in user
    assert "linked-list" in user
    assert "node-link-visual" in user
    assert "모든 bullet 문장마다" in user
    assert "각 script_text마다" in user
    assert "각 bullet은 45자 이상" in user
    assert "title/focus/checkpoint/category/html/css" in user
    assert "완전한 한국어 문장 4~7개" in user


def test_voice_expansion_prompt_pins_tts_delivery_contract() -> None:
    system = _voice_expansion_system()
    user = _user_prompt(
        12,
        learner_profile="학습자",
        weak_points="혼동행렬, FP, FN",
        reference_context_prompt="참고도서 p.7",
        voice_expansion_planned=True,
    )

    assert "TTS용 1:1 과외 음성대본" in system
    assert "SSML" in system
    assert "요.', '다.', '죠.'" in system
    assert "FP, 에프 피, 거짓 양성" in system
    assert "voice_scripts는 2차 TTS 대본 확장" in user
    assert "5~7문장" in user


def test_voice_segment_prompt_pins_json_and_tts_contract() -> None:
    system = _voice_segment_system()

    assert "slide_idx, segment_idx, segment_text" in system
    assert "230~520자" in system
    assert "SSML" in system


def test_voice_full_rewrite_prompt_forces_complete_tts_script() -> None:
    payload = LessonPayload.model_validate(_payload(10))
    prompt = _voice_full_rewrite_user(
        payload,
        payload.slides[4],
        payload.voice_scripts[4],
        learner_profile="학습자",
        weak_points="혼동행렬, FP",
        reference_context_prompt="참고도서 p.7",
        retry_reason="짧음",
    )

    assert "전체 대본을 새로 작성" in prompt
    assert "850자 미만이면 실패" in prompt
    assert "초안 대본" not in prompt
    assert payload.voice_scripts[4].script_text not in prompt
    assert "자," in prompt
    assert "오답 함정" in prompt
    assert "에프 피" in prompt


def test_expand_voice_can_limit_modal_calls_to_one_slide(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    payload = LessonPayload.model_validate(_payload(10))
    good_script = _good_voice_script()
    calls: list[list[object]] = []

    class FakeConnector:
        async def generate_batch(self, reqs: list[object]) -> list[ChapterAIResponse]:
            calls.append(reqs)
            return [
                ChapterAIResponse(
                    text=json.dumps({"slide_idx": 4, "script_text": good_script}, ensure_ascii=False),
                    model="fake",
                    input_tokens=10,
                    output_tokens=20,
                    finish_reason="stop",
                )
            ]

    monkeypatch.setattr(actual_eval, "Qwen27BModalConnector", FakeConnector)
    meta = {"input_tokens": 0, "output_tokens": 0, "wall_sec": 0.0}
    expanded = asyncio.run(
        _expand_voice_scripts(
            payload,
            out_dir=tmp_path,
            meta=meta,
            learner_profile="학습자",
            weak_points="혼동행렬, FP",
            reference_context_prompt="참고도서 p.7",
            target_slide_idx=4,
        )
    )

    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert expanded.voice_scripts[4].script_text == good_script
    assert expanded.voice_scripts[3].script_text == payload.voice_scripts[3].script_text
    assert meta["voice_expansion"]["calls"] == 1


def test_expand_voice_segmented_only_merges_four_parallel_segments(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    payload = LessonPayload.model_validate(_payload(10))
    segments = _good_voice_segments()
    calls: list[list[object]] = []

    class FakeConnector:
        async def generate_batch(self, reqs: list[object]) -> list[ChapterAIResponse]:
            calls.append(reqs)
            return [
                ChapterAIResponse(
                    text=json.dumps({"slide_idx": 4, "segment_idx": idx, "segment_text": text}, ensure_ascii=False),
                    model="fake",
                    input_tokens=10,
                    output_tokens=20,
                    finish_reason="stop",
                )
                for idx, text in enumerate(segments)
            ]

    monkeypatch.setattr(actual_eval, "Qwen27BModalConnector", FakeConnector)
    meta = {"input_tokens": 0, "output_tokens": 0, "wall_sec": 0.0}
    expanded = asyncio.run(
        _expand_voice_scripts(
            payload,
            out_dir=tmp_path,
            meta=meta,
            learner_profile="학습자",
            weak_points="혼동행렬, FP, FN",
            reference_context_prompt="참고도서 p.9",
            target_slide_idx=4,
            segmented_only=True,
        )
    )

    assert len(calls) == 1
    assert len(calls[0]) == 4
    assert expanded.voice_scripts[4].script_text == _merge_voice_segments(segments)
    assert not _voice_script_needs_retry(expanded.voice_scripts[4].script_text)
    assert meta["voice_expansion"]["remaining_retry_targets"] == []


def test_payload_replay_guard_blocks_accidental_full_voice_expansion() -> None:
    payload = LessonPayload.model_validate(_payload(15))
    args = SimpleNamespace(
        slide_count=15,
        expand_voice=True,
        voice_slide_idx=-1,
        allow_full_voice_expansion=False,
        voice_segmented_only=False,
    )

    with pytest.raises(ValueError, match="전체 음성 재확장"):
        _validate_payload_replay_args(args, payload)


def test_payload_replay_guard_blocks_slide_count_mismatch() -> None:
    payload = LessonPayload.model_validate(_payload(15))
    args = SimpleNamespace(
        slide_count=12,
        expand_voice=True,
        voice_slide_idx=4,
        allow_full_voice_expansion=False,
        voice_segmented_only=False,
    )

    with pytest.raises(ValueError, match="slide-count 불일치"):
        _validate_payload_replay_args(args, payload)


def test_payload_replay_guard_requires_expand_voice_for_segmented_only() -> None:
    payload = LessonPayload.model_validate(_payload(15))
    args = SimpleNamespace(
        slide_count=15,
        expand_voice=False,
        voice_slide_idx=4,
        allow_full_voice_expansion=False,
        voice_segmented_only=True,
    )

    with pytest.raises(ValueError, match="voice-segmented-only"):
        _validate_payload_replay_args(args, payload)


def test_parse_single_voice_segment_accepts_segment_object() -> None:
    parsed = _parse_single_voice_segment('{"slide_idx": 3, "segment_idx": 2, "segment_text": "문단입니다."}', 3, 2)

    assert parsed.slide_idx == 3
    assert parsed.segment_idx == 2
    assert parsed.segment_text == "문단입니다."


def test_supporting_repair_prompt_pins_quiz_assignment_scope() -> None:
    system = _supporting_repair_system(15)

    assert "퀴즈와 과제 보강기" in system
    assert "quizzes, assignment" in system
    assert "약점 연결" in system


def test_tts_delivery_style_requires_tutor_tone_and_pronunciation() -> None:
    good = (
        "자, 여기서는 FP, 에프 피, 거짓 양성을 먼저 잡아야 해요. "
        "한 번 멈춰서 생각해봅시다. 실전에서는 오답 함정은 정확도만 보는 습관에서 나옵니다. "
        "이 약점은 혼동행렬을 표로 다시 보는 연습으로 줄일 수 있어요. "
        "p.7을 다시 보면 판단 기준이 연결됩니다. 마지막으로 에프 엔도 함께 떠올리면 됩니다. "
        "따라서 문제에서는 먼저 양성과 음성을 나누면 되죠. 이제 짧게 직접 설명해 보세요."
    )
    bad = "FP/FN이 중요합니다. 외우면 됩니다."

    assert _has_tts_delivery_style(good)
    assert not _has_tts_delivery_style(bad)


def test_voice_retry_gate_rejects_short_summary() -> None:
    assert _voice_script_needs_retry("짧은 요약입니다. p.7을 보세요.")


def test_parse_single_voice_script_accepts_direct_object() -> None:
    parsed = _parse_single_voice_script('{"slide_idx": 3, "script_text": "대본입니다."}', 3)

    assert parsed.slide_idx == 3
    assert parsed.script_text == "대본입니다."


def test_actual_lesson_payload_requires_exact_slide_voice_and_quiz_count() -> None:
    payload = _payload(10)
    parsed = _parse_payload(json.dumps(payload, ensure_ascii=False), 10)

    assert len(parsed.slides) == 10
    assert len(parsed.quizzes) == 10
    assert len(parsed.voice_scripts) == 10


def test_actual_lesson_payload_rejects_missing_voice_index() -> None:
    payload = _payload(10)
    payload["voice_scripts"] = payload["voice_scripts"][:-1]

    with pytest.raises(ValueError, match="개수 계약 불일치|JSON 검증 실패"):
        _parse_payload(json.dumps(payload, ensure_ascii=False), 10)


def test_scale_contract_scores_actual_lesson_storage_mapping() -> None:
    result = {
        "slides": [{"slide_idx": idx} for idx in range(10)],
        "voice_scripts": [{"slide_idx": idx} for idx in range(10)],
        "quizzes": [{"slide_idx": idx} for idx in range(10)],
        "note_blocks": [{"heading": "핵심", "bullets": ["a", "b"]} for _ in range(3)],
        "storage_preview": [
            {"table": "chapter_studio.slide"},
            {"table": "chapter_studio.quiz"},
            {"table": "chapter_studio.note"},
            {"table": "chapter_studio.assignment"},
            {"table": "chapter_studio.voice_script"},
            {"table": "chapter_studio.voice_script_queue"},
        ],
    }

    score, note = _score_scale_contract(result, 10)

    assert score == 15
    assert "slides=10" in note


def test_ops_score_accepts_practical_b200_cost_window() -> None:
    score, note = _score_ops(
        {
            "wall_sec": 600.0,
            "estimated_b200_gpu_cost_usd": 1.0416,
            "estimated_b200_gpu_cost_with_scaledown_usd": 1.25,
        }
    )

    assert score == 10
    assert "gpu=$1.0416" in note


def test_tts_sentence_count_ignores_page_reference_period() -> None:
    text = "p.7을 다시 보면 흐름이 보입니다. p.8의 표를 확인합니다. p.9와 연결합니다. 네 번째입니다. 다섯 번째입니다. 여섯 번째입니다."

    assert _tts_sentence_count(text) == 6


def test_slide_sentence_gate_allows_code_and_structured_visuals() -> None:
    code_html = "문장입니다. " * 13
    flow_html = '<div class="flow-strip">' + ("문장입니다. " * 9) + "</div>"
    plain_html = "문장입니다. " * 9

    assert _slide_sentence_ok({"category": "code"}, code_html)
    assert _slide_sentence_ok({"category": "diagram"}, flow_html)
    assert not _slide_sentence_ok({"category": "text"}, plain_html)


def test_extract_json_object_prefers_json_after_stray_think_close() -> None:
    text = '{"broken": [1]\n</think>\n{"slides": [], "quizzes": []}'

    assert _extract_json_object(text) == '{"slides": [], "quizzes": []}'


def _payload(slide_count: int) -> dict[str, object]:
    quiz = {
        "slide_idx": 0,
        "question": "문제",
        "choices": ["A", "B", "C", "D"],
        "answer_idx": 0,
        "difficulty": "중",
        "explanation": "정답 근거와 오답 이유를 충분히 설명합니다.",
    }
    return {
        "slides": [
            {
                "slide_idx": idx,
                "title": f"{idx}장",
                "focus": "핵심 판단",
                "checkpoint": "스스로 설명할 수 있는가?",
                "category": "text",
                "html": "<section><h2>핵심</h2><p>충분한 설명입니다.</p></section>",
                "css": "",
            }
            for idx in range(slide_count)
        ],
        "quizzes": [{**quiz, "slide_idx": idx} for idx in range(slide_count)],
        "note_blocks": [{"heading": "핵심", "bullets": ["p.7 기준", "복습 문장"]} for _ in range(3)],
        "assignment": {
            "title": "과제",
            "assignment_format": "문제풀이+근거 표시",
            "expected_minutes": 25,
            "steps": ["분석하세요.", "비교하세요.", "서술하세요."],
            "rubric": ["정확성", "근거", "완성도"],
        },
        "voice_scripts": [
            {"slide_idx": idx, "script_text": "첫 문장입니다. 둘째 문장입니다. 셋째 문장입니다. 넷째 문장입니다. 다섯째 문장입니다."}
            for idx in range(slide_count)
        ],
    }


def _good_voice_script() -> str:
    return (
        "자, 여기서는 혼동행렬을 시험장에서 어떻게 읽을지부터 잡아볼게요. "
        "p.7을 다시 보면 예측값과 실제값을 가로세로로 나누는 표가 나오는데, 이 표가 정밀도와 재현율의 출발점입니다. "
        "여기서 FP, 에프 피, 거짓 양성은 정상 메일을 스팸이라고 잘못 잡은 경우라고 이해하면 됩니다. "
        "한 번 멈춰서 생각해봅시다, 스팸 필터 문제에서는 사용자가 놓치면 안 되는 정상 메일을 줄이는 판단이 더 중요할 수 있어요. "
        "실전에서는 정확도만 먼저 보지 말고, 어떤 오류가 더 치명적인지 문제 문장 속 비용을 보고 판단해야 합니다. "
        "오답 함정은 전체 정답률이 높다는 말만 보고 FP와 FN, 에프 엔, 거짓 음성의 차이를 무시하는 데서 나옵니다. "
        "이 약점은 혼동행렬의 네 칸을 말로 바꾸는 연습을 하면 빠르게 줄일 수 있습니다. "
        "지금 20초 동안 정상 메일을 스팸으로 오분류한 사례를 하나 떠올리고, 그것이 왜 에프 피인지 직접 설명해 보세요. "
        "판단 근거를 말할 때는 p.8의 표처럼 분모가 무엇인지 함께 확인하면 실수가 줄어듭니다. "
        "예를 들어 실제 스팸은 맞췄지만 정상 메일을 잃어버리는 상황이라면, 모델 점수가 좋아 보여도 서비스에서는 위험하다고 말할 수 있어야 합니다. "
        "그래서 정밀도를 볼 때는 모델이 스팸이라고 잡은 것들 중 정말 스팸이 얼마나 되는지를 먼저 확인합니다. "
        "반대로 재현율을 볼 때는 실제 스팸 전체 중 얼마나 놓치지 않았는지를 묻는다고 바꿔 말하면 됩니다. "
        "이렇게 질문을 바꾸면 정확도 하나만 보는 습관에서 벗어나고, 문제의 비용 조건과 지표 선택을 자연스럽게 연결할 수 있습니다. "
        "마지막으로 다음 슬라이드에서는 이 오류 감각을 과대적합 방지와 연결해서, 훈련 점수만 좋은 모델을 어떻게 의심할지 차분히 다시 보겠습니다."
    )


def _good_voice_segments() -> list[str]:
    return [
        (
            "자, 여기서 정확도를 볼 때 먼저 화면의 분자와 분모를 말로 바꿔 보겠습니다. "
            "정확도는 전체 예측 중 맞춘 비율이라서 직관적으로 쉬워 보이지만, 이 쉬움 때문에 실전에서 가장 많이 속습니다. "
            "p.9를 다시 보면 혼동행렬의 네 칸을 먼저 확인해야 지표 해석이 흔들리지 않는다는 점이 연결됩니다. "
            "판단 순서는 전체 정답률을 본 뒤 바로 멈추는 것이 아니라, 어떤 칸에서 오류가 생겼는지까지 이어져야 합니다."
        ),
        (
            "예를 들어 양성 샘플이 1퍼센트뿐인 데이터에서 모델이 전부 음성이라고 말하면 정확도는 높게 나옵니다. "
            "하지만 실제 양성을 모두 놓쳤으므로 FN, 에프 엔, 거짓 음성이 크게 발생하고 재현율은 무너집니다. "
            "한 번 멈춰서 생각해봅시다, 높은 정확도가 항상 좋은 모델이라는 말은 이 상황에서 바로 깨집니다. "
            "이처럼 클래스 불균형 문제에서는 정확도보다 놓친 양성의 수가 더 직접적인 위험 신호가 됩니다."
        ),
        (
            "실전에서는 문제 문장에서 어떤 오류의 비용이 더 큰지 먼저 판단해야 합니다. "
            "오답 함정은 정확도 숫자만 보고 FP, 에프 피, 거짓 양성과 FN, 에프 엔, 거짓 음성을 따로 보지 않는 것입니다. "
            "이 약점은 혼동행렬을 지표와 연결하는 연습으로 줄일 수 있고, 정밀도와 재현율을 함께 말해야 안정적입니다. "
            "특히 스팸 필터와 질병 진단처럼 비용 구조가 다른 예시는 어떤 지표를 우선할지 판단하게 해줍니다."
        ),
        (
            "20초 미니연습을 해봅시다, 양성 10개와 음성 990개에서 모두 음성으로 예측하면 정확도와 FN이 어떻게 되는지 계산해 보세요. "
            "정답은 정확도 99퍼센트, FN, 에프 엔, 거짓 음성 10개이며, 이 모델은 양성을 찾는 문제에서는 실패입니다. "
            "마지막으로 다음 슬라이드에서는 이 판단을 과대적합 방지와 연결해, 점수만 좋은 모델을 어떻게 의심할지 보겠습니다. "
            "오늘의 핵심은 정확도를 버리는 것이 아니라, 혼동행렬과 함께 읽어야 실전 판단이 된다는 점입니다."
        ),
    ]
