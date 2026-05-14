from __future__ import annotations

from app.modules.ChapterStudio_V1.scripts.run_modal_quality_eval import (
    _count_refs,
    _extract_ref_pages,
    _score,
    _score_assignment,
    _score_lesson_contract,
    _score_notes,
    _score_references,
    _score_slides,
    _score_visual_gates,
)


def test_assignment_score_counts_data_analysis_action_verbs() -> None:
    score, note = _score_assignment(
        {
            "assignment": {
                "assignment_format": "문제풀이+근거 표시",
                "expected_minutes": 20,
                "steps": [
                    "데이터를 탐색하고 이상값을 확인한 뒤 관계를 분석하세요. (p.7)",
                    "로지스틱 회귀와 의사결정나무 모델을 구축하세요. (p.8)",
                    "혼동행렬을 비교하고 재현율을 계산한 뒤 선택 근거를 서술하세요. (p.9)",
                ],
                "rubric": ["p.7 근거", "p.8 근거", "p.9 근거"],
            }
        }
    )

    assert score == 10
    assert "format=True" in note
    assert "expected_minutes=20" in note
    assert "행동동사 3" in note


def test_count_refs_expands_page_ranges() -> None:
    assert _count_refs(["p.7~p.9를 읽고 페이지 15도 확인한다."]) == 4


def test_extract_ref_pages_expands_ranges_without_duplicates() -> None:
    assert _extract_ref_pages(["p.7~p.9를 읽고 p.8과 페이지 15를 확인한다."]) == {7, 8, 9, 15}


def test_note_reference_score_accepts_one_page_anchor_per_note_block() -> None:
    result = {
        "note_blocks": [
            {
                "heading": "탐색",
                "bullets": [
                    "p.7의 결측값과 정규화 키워드는 전처리 문제에서 먼저 확인할 판단 기준이며, 보기에서 처리 순서를 흔들 때 다시 읽어야 합니다.",
                    "EDA 결과를 보고 변수 변환 필요성을 설명할 수 있어야 하며, 단순 그래프 해석보다 모델 입력 품질과 연결해야 합니다.",
                    "시험에서는 처리 순서를 묻는 선택지가 자주 흔들리므로, 탐색과 정제의 목적 차이를 문장으로 구분해야 합니다.",
                ],
            },
            {
                "heading": "모델링",
                "bullets": [
                    "p.8의 회귀분석과 의사결정나무는 모델 선택 근거를 비교할 때 다시 보며, 선형성 여부와 해석 가능성을 함께 확인합니다.",
                    "과대적합은 모델 성능이 아니라 일반화 기준으로 설명해야 하며, 훈련 점수만 높은 상황을 경계해야 합니다.",
                    "배깅과 부스팅은 오류 감소 관점에서 구분하고, 문제에서 안정성인지 성능 개선인지 먼저 표시해야 합니다.",
                ],
            },
            {
                "heading": "평가",
                "bullets": [
                    "p.9의 혼동행렬과 F1 Score는 최종 판단 지표를 고르는 핵심 근거이며, 어떤 오류가 더 큰지와 연결해야 합니다.",
                    "재현율과 정밀도는 문제 상황의 비용 차이와 연결해서 보고, 양성 탐지가 중요한지 오탐 감소가 중요한지 구분합니다.",
                    "교차검증은 새 데이터에서의 안정성을 확인하는 절차이므로, 한 번의 테스트 점수만으로 결론 내리지 않습니다.",
                ],
            },
        ]
    }

    score, note = _score_notes(result)

    assert score == 15
    assert "p.참조 3" in note


def test_reference_score_uses_note_block_page_anchors() -> None:
    result = {
        "note_blocks": [
            {"heading": "탐색", "bullets": ["p.7 전처리 기준을 다시 읽습니다."]},
            {"heading": "모델링", "bullets": ["p.8 모델 선택 기준을 다시 읽습니다."]},
            {"heading": "평가", "bullets": ["p.9 평가 지표를 다시 읽습니다."]},
        ],
        "voice_scripts": [
            {"script_text": "p.7에서 전처리 기준을 확인합니다."},
            {"script_text": "p.8에서 모델링 기준을 확인합니다."},
            {"script_text": "p.9에서 평가 지표를 확인합니다."},
            {"script_text": "p.15에서 최종 모형 선정 기준을 확인합니다."},
        ],
        "assignment": {
            "steps": ["p.7~p.9를 근거로 표를 채우고 페이지 15의 최종 기준과 비교하세요."],
        },
        "reference_pages": [7, 8, 9, 15],
    }

    score, note = _score_references(result)

    assert score == 10
    assert "암기노트 3" in note
    assert "미검증 페이지" not in note


def test_reference_score_rejects_pages_absent_from_ocr_context() -> None:
    result = {
        "note_blocks": [
            {"heading": "탐색", "bullets": ["p.7 전처리 기준을 다시 읽습니다."]},
            {"heading": "모델링", "bullets": ["p.8 모델 선택 기준을 다시 읽습니다."]},
            {"heading": "평가", "bullets": ["p.999 환각 페이지를 다시 읽습니다."]},
        ],
        "voice_scripts": [{"script_text": "p.7에서 기준을 확인합니다."} for _ in range(4)],
        "assignment": {"steps": ["p.7~p.9를 근거로 비교하세요."]},
        "reference_pages": [7, 8, 9],
    }

    score, note = _score_references(result)

    assert score < 10
    assert "미검증 페이지 [999]" in note


def test_reference_score_does_not_require_ocr_page_whitelist_when_no_reference_book() -> None:
    result = {
        "note_blocks": [
            {"heading": "탐색", "bullets": ["p.7 전처리 기준을 다시 읽습니다."]},
            {"heading": "모델링", "bullets": ["p.8 모델 선택 기준을 다시 읽습니다."]},
            {"heading": "평가", "bullets": ["p.9 평가 지표를 다시 읽습니다."]},
        ],
        "voice_scripts": [{"script_text": "p.7에서 기준을 확인합니다."} for _ in range(4)],
        "assignment": {"steps": ["p.7~p.9를 근거로 비교하세요."]},
        "reference_pages": [],
    }

    score, note = _score_references(result)

    assert score == 10
    assert "미검증 페이지" not in note


def test_slide_score_requires_code_token_theme() -> None:
    payload = {
        "slides": [
            {"slide_idx": 0, "category": "text", "html": "<p>문장입니다. 문장입니다. 문장입니다. 문장입니다. 문장입니다. 문장입니다. 문장입니다.</p><ul><li>a</li><li>b</li></ul>"}
            for _ in range(5)
        ]
    }
    for idx, slide in enumerate(payload["slides"]):
        slide["slide_idx"] = idx
    result = {"slides": [{"iframe_html": "<code>x</code>"} for _ in range(5)]}
    score_without_theme, _ = _score_slides(payload, result)
    result["slides"][0]["iframe_html"] = '<div class="code-card"><code><span class="tok-keyword">def</span> x</code></div>'
    score_with_theme, _ = _score_slides(payload, result)

    assert score_with_theme > score_without_theme


def test_visual_gate_requires_per_slide_rendered_slots() -> None:
    result = {
        "slides": [
            _slide(0, '<img class="rendered-chart" src="data:image/png;base64,abc" /><div class="metric-card"></div>'),
            _slide(1, '<div class="mermaid-fallback"><div class="mermaid-node"></div></div>'),
            _slide(2, '<div class="code-card"><span class="tok-keyword">def</span></div><div class="formula">x = y</div>'),
            _slide(3, '<div class="flow-strip"></div>'),
            _slide(4, '<details open><summary>실습</summary></details>'),
        ]
    }

    score, note = _score_visual_gates({}, result)

    assert score == 10
    assert note == "PASS"


def test_visual_gate_fails_raw_chart_and_missing_slot() -> None:
    result = {
        "slides": [
            _slide(0, '<div class="chart-box" data-chart-type="bar" data-chart-spec="{}"></div>'),
            _slide(1, '<pre class="mermaid">flowchart LR\\nA-->B</pre>'),
            _slide(2, '<pre><code>print(1)</code></pre><div class="formula">x</div>'),
            _slide(3, "<p>텍스트만 있습니다.</p>"),
            _slide(4, "<p>실습 없음</p>"),
        ]
    }

    score, note = _score_visual_gates({}, result)

    assert score < 10
    assert "slide0 차트 렌더" in note
    assert "렌더되지 않은 raw 시각 블록" in note


def test_score_treats_postprocess_warning_as_critical_failure() -> None:
    payload = {
        "slides": [
            {
                "slide_idx": idx,
                "category": "text",
                "html": "<p>문장입니다. 문장입니다. 문장입니다. 문장입니다. 문장입니다. 문장입니다. 문장입니다.</p><ul><li>a</li><li>b</li></ul>",
            }
            for idx in range(5)
        ]
    }
    result = {
        "slides": [
            _slide(0, '<img class="rendered-chart" src="data:image/png;base64,abc" /><div class="metric-card"></div>'),
            _slide(1, '<div class="mermaid-fallback"><div class="mermaid-node"></div></div>'),
            _slide(2, '<div class="code-card"><span class="tok-keyword">def</span></div><div class="formula">x = y</div>'),
            _slide(3, '<div class="flow-strip"></div>'),
            _slide(4, '<details open><summary>실습</summary></details>'),
        ],
        "voice_scripts": [{"script_text": "문장입니다. " * 6, "slide_idx": idx} for idx in range(5)],
        "note_blocks": [{"heading": "h", "bullets": ["p.1 " + "깊은 설명입니다. " * 5 for _ in range(5)]}],
        "assignment": {
            "title": "과제",
            "assignment_format": "서술형 복습지",
            "expected_minutes": 20,
            "steps": ["분석하세요. p.1", "비교하세요. p.2", "설명하세요. p.3"],
            "rubric": ["p.1", "p.2", "p.3"],
        },
        "quizzes": [
            {"choices": ["a", "b", "c", "d"], "explanation": "충분한 해설입니다. " * 8, "difficulty": "중"}
            for _ in range(5)
        ],
    }

    scorecard = _score(payload, result, "", ["visual-density: 차트 원문 블록이 렌더링되지 않아 시각자료가 완성되지 않았다."])

    assert scorecard["pass"] is False
    assert "후처리 경고" in scorecard["critical_failures"]


def test_lesson_contract_requires_four_core_deliverables() -> None:
    result = {
        "slides": [
            {
                "slide_idx": idx,
                "iframe_html": "<!DOCTYPE html><html><body><section>슬라이드</section></body></html>",
            }
            for idx in range(5)
        ],
        "voice_scripts": [{"slide_idx": idx, "script_text": "과외식으로 설명합니다."} for idx in range(5)],
        "note_blocks": [
            {"heading": "핵심", "bullets": ["핵심 개념을 다시 떠올리는 정리 문장입니다.", "다시 볼 기준을 남기는 복습 문장입니다."]},
            {"heading": "복습", "bullets": ["복습할 때 먼저 확인해야 할 문장입니다.", "오답을 고칠 때 기준으로 쓸 문장입니다."]},
            {"heading": "적용", "bullets": ["실전 문제에 적용할 때 사용할 문장입니다.", "다음 학습으로 이어갈 기준 문장입니다."]},
        ],
        "assignment": {
            "title": "과제",
            "assignment_format": "표 채우기",
            "expected_minutes": 20,
            "steps": ["분석하세요.", "비교하세요.", "설명하세요."],
            "rubric": ["정확성", "근거", "완성도"],
        },
        "storage_preview": [
            {"table": "chapter_studio.slide"},
            {"table": "chapter_studio.note"},
            {"table": "chapter_studio.assignment"},
            {"table": "chapter_studio.voice_script"},
            {"table": "chapter_studio.voice_script_queue"},
        ],
    }

    score, note = _score_lesson_contract(result)

    assert score == 10
    assert note == "PASS"


def test_lesson_contract_fails_assignment_without_format() -> None:
    result = {
        "slides": [{"slide_idx": idx, "iframe_html": "<!DOCTYPE html><html></html>"} for idx in range(5)],
        "voice_scripts": [{"slide_idx": idx, "script_text": "대본입니다."} for idx in range(5)],
        "note_blocks": [{"heading": "핵심", "bullets": ["핵심 정리 문장입니다.", "다시 볼 문장입니다."]}],
        "assignment": {"title": "과제", "steps": ["a", "b", "c"], "rubric": ["a", "b", "c"]},
        "storage_preview": [],
    }

    score, note = _score_lesson_contract(result)

    assert score < 10
    assert "과제 형식" in note


def _slide(index: int, iframe_html: str) -> dict[str, object]:
    return {"slide_idx": index, "iframe_html": iframe_html}
