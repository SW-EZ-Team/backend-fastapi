"""강의 산출물 경량 self-check.

generate_node가 parse 성공 직후 호출하는 품질 점검 함수 모음이다. 모델이 codex(gpt-5.5)→
Qwen3.6(Modal)→Claude로 바뀌어도 분량·구조 하한이 무너지지 않도록, 주제에 종속되지 않는
일반 휴리스틱으로만 미달 항목을 찾는다. 여기서는 어떤 LLM도 호출하지 않으며(순수 함수),
미달 보고(Deficiency)만 만들어 repair 단계가 소비하도록 한다.

공개 API:
    - check_payload(payload) : 미달 항목 목록(Deficiencies)을 반환한다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from html import unescape

from app.modules.ChapterStudio_V1.pipeline.payload import GeneratedLessonPayload

# 음성대본 품질 하한 — 약한 모델의 한두 문장 통과를 막는다(스키마 하한 40자보다 엄격).
VOICE_MIN_CHARS = 700
VOICE_MIN_SENTENCES = 7
# 퀴즈 해설 품질 하한.
EXPLANATION_MIN_CHARS = 100
# 노트 bullet 완결성 하한.
NOTE_BULLET_MIN_CHARS = 40
# 슬라이드 본문 완결 문장 하한.
SLIDE_MIN_SENTENCES = 3
SLIDE_MIN_PLAIN_CHARS = 120

# category별 후처리(render) 체인이 기대하는 필수 마커. postprocess._has_meaningful_visual과
# 같은 어휘를 쓰되, 생성 단계에서 원본 소스 마커를 확인한다.
_CATEGORY_MARKERS: dict[str, tuple[str, ...]] = {
    "diagram": ("<pre", "<svg", "visual-slide", "concept-map-visual", "step-flow-visual"),
    "code": ("<pre", "<code"),
    "math": ("formula", "katex", "$", "<svg", "number-line-visual", "fraction-bar-visual"),
    "chart": ("chart-box", "data-chart-spec", "<svg", "comparison-visual"),
    "table": ("<table",),
    "interactive": ("<details", "step-grid", "node-link-visual", "linked-list", "graph-map"),
}
_SENTENCE_BOUNDARY = re.compile(r"[.!?。…]+|\n")


@dataclass(frozen=True)
class Deficiency:
    """repair 단계가 소비할 단일 미달 항목.

    field: voice / explanation / note / slide_html 중 하나(어떤 산출물인지).
    slide_idx: 슬라이드/퀴즈/대본 인덱스(노트는 -1).
    reason: 사람이 읽을 수 있는 미달 사유(프롬프트에 그대로 넣는다).
    """

    field: str
    slide_idx: int
    reason: str


@dataclass(frozen=True)
class QualityReport:
    """payload 한 개에 대한 self-check 결과 묶음."""

    deficiencies: list[Deficiency] = field(default_factory=list)

    def is_ok(self) -> bool:
        return not self.deficiencies

    def voice_targets(self) -> set[int]:
        return {d.slide_idx for d in self.deficiencies if d.field == "voice"}

    def supporting_needs_repair(self) -> bool:
        return any(d.field in {"explanation", "note"} for d in self.deficiencies)


def check_payload(payload: GeneratedLessonPayload) -> QualityReport:
    """강의 산출물 전체를 점검해 미달 항목 목록을 만든다."""
    items: list[Deficiency] = []
    items.extend(_check_quizzes(payload))
    items.extend(_check_voice(payload))
    items.extend(_check_notes(payload))
    items.extend(_check_slides(payload))
    return QualityReport(deficiencies=items)


def _check_quizzes(payload: GeneratedLessonPayload) -> list[Deficiency]:
    items: list[Deficiency] = []
    for quiz in payload.quizzes:
        # answer_idx가 choices 범위를 벗어나면 정답 위치 자체가 깨진 것이다.
        if not 0 <= quiz.answer_idx < len(quiz.choices):
            items.append(Deficiency("explanation", quiz.slide_idx, "answer_idx가 choices 범위를 벗어났다."))
            continue
        if len(quiz.explanation.strip()) < EXPLANATION_MIN_CHARS:
            items.append(
                Deficiency(
                    "explanation",
                    quiz.slide_idx,
                    f"해설이 {len(quiz.explanation.strip())}자로 짧다(목표 120~180자, 오답 함정·약점 연결 포함).",
                )
            )
    return items


def _check_voice(payload: GeneratedLessonPayload) -> list[Deficiency]:
    items: list[Deficiency] = []
    for script in payload.voice_scripts:
        text = script.script_text.strip()
        sentences = _sentence_count(text)
        if len(text) < VOICE_MIN_CHARS or sentences < VOICE_MIN_SENTENCES:
            items.append(
                Deficiency(
                    "voice",
                    script.slide_idx,
                    f"대본이 {len(text)}자/{sentences}문장으로 얕다(목표 900~1600자, 8~12문장, 과외 말투).",
                )
            )
    return items


def _check_notes(payload: GeneratedLessonPayload) -> list[Deficiency]:
    shallow = sum(
        1
        for block in payload.note_blocks
        for bullet in block.bullets
        if len(bullet.strip()) < NOTE_BULLET_MIN_CHARS
    )
    if shallow:
        return [Deficiency("note", -1, f"note bullet {shallow}개가 45자 미만으로 얕다(완결 문장 필요).")]
    return []


def _check_slides(payload: GeneratedLessonPayload) -> list[Deficiency]:
    items: list[Deficiency] = []
    for slide in payload.slides:
        plain = _plain_text(slide.html)
        sentences = _sentence_count(plain)
        if _has_structured_visual(slide.html):
            missing = _missing_category_marker(slide.category, slide.html)
            if missing:
                items.append(Deficiency("slide_html", slide.slide_idx, f"category={slide.category} 필수 시각요소({missing}) 누락."))
            continue
        if len(plain) < SLIDE_MIN_PLAIN_CHARS or sentences < SLIDE_MIN_SENTENCES:
            items.append(
                Deficiency(
                    "slide_html",
                    slide.slide_idx,
                    f"본문이 {len(plain)}자/{sentences}문장으로 얕다(완전한 문장 4~7개 필요).",
                )
            )
            continue
        missing = _missing_category_marker(slide.category, slide.html)
        if missing:
            items.append(Deficiency("slide_html", slide.slide_idx, f"category={slide.category} 필수 시각요소({missing}) 누락."))
    return items


def _has_structured_visual(html: str) -> bool:
    markers = ("visual-slide", "number-line-visual", "comparison-visual", "step-flow-visual", "fraction-bar-visual", "concept-map-visual", "example-box-visual")
    return any(marker in html for marker in markers)


def _missing_category_marker(category: str, html: str) -> str:
    markers = _CATEGORY_MARKERS.get(category)
    if not markers:
        return ""
    if any(marker in html for marker in markers):
        return ""
    return " 또는 ".join(markers)


def _sentence_count(text: str) -> int:
    # 페이지 표기 p.7의 마침표를 문장 경계로 오판하지 않게 한다.
    normalized = re.sub(r"\bp\.(\d+)", r"p\1", text)
    parts = [part.strip() for part in _SENTENCE_BOUNDARY.split(normalized)]
    return sum(1 for part in parts if len(part) >= 4)


def _plain_text(html: str) -> str:
    without_style = re.sub(r"<style[^>]*>.*?</style>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    without_tags = re.sub(r"<[^>]+>", " ", without_style)
    return re.sub(r"\s+", " ", unescape(without_tags)).strip()


__all__ = ["Deficiency", "QualityReport", "check_payload"]
