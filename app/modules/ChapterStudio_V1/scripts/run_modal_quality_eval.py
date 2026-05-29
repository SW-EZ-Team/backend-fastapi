"""ChapterStudio 품질 점수 유틸리티.

실행형 Modal 평가 스크립트는 프로덕션 그래프와 분리되었고, 이 파일은
기존 리포트/회귀 테스트가 쓰는 순수 점수 함수만 유지한다.
"""
from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

DEFAULT_OCR_JSONL = Path(__file__).resolve().parents[1] / "artifacts" / "real_pdf_ocr" / "ocr.jsonl"
_PAGE_RE = re.compile(r"(?:p\.?|페이지)\s*(\d+)(?:\s*(?:~|-|–|—)\s*(?:p\.?|페이지)?\s*(\d+))?")
_ACTION_RE = re.compile(r"(작성|비교|계산|분류|점검|설명|표시|풀|분석|구축|처리|해석|선택|서술|확인|탐색|평가|도출|적용)")


@dataclass(frozen=True)
class ReferenceHit:
    page: int
    snippet: str


@dataclass(frozen=True)
class ReferenceContext:
    hits: list[ReferenceHit]

    def has_hits(self) -> bool:
        return bool(self.hits)


def _h(value: str) -> str:
    return html.escape(value, quote=True)


def _sentence_count(value: str) -> int:
    normalized = re.sub(r"p\.(\d+)", r"p\1", value)
    return len([part for part in re.split(r"[.!?。！？]|다\.|요\.", normalized) if part.strip()])


def _reference_context(path: Path) -> ReferenceContext:
    if not path.exists():
        return ReferenceContext([])
    hits: list[ReferenceHit] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        hit = _hit_from_line(line)
        if hit is not None:
            hits.append(hit)
    return ReferenceContext(hits)


def _reference_pages(context: ReferenceContext) -> list[int]:
    return sorted({hit.page for hit in context.hits})


def _hit_from_line(line: str) -> ReferenceHit | None:
    try:
        data = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    page = data.get("page") or data.get("page_number")
    text = data.get("text") or data.get("snippet") or ""
    if not isinstance(page, int) or not isinstance(text, str):
        return None
    return ReferenceHit(page=page, snippet=text)


def _extract_ref_pages(values: list[str]) -> set[int]:
    pages: set[int] = set()
    for value in values:
        for match in _PAGE_RE.finditer(value):
            start = int(match.group(1))
            end = int(match.group(2) or start)
            low, high = sorted((start, end))
            pages.update(range(low, high + 1))
    return pages


def _count_refs(values: list[str]) -> int:
    return len(_extract_ref_pages(values))


def _score_assignment(result: dict[str, object]) -> tuple[int, str]:
    assignment = _dict(result.get("assignment"))
    steps = _str_list(assignment.get("steps"))
    rubric = _str_list(assignment.get("rubric"))
    has_format = bool(assignment.get("assignment_format"))
    minutes = assignment.get("expected_minutes")
    minutes_ok = isinstance(minutes, int) and 10 <= minutes <= 60
    action_count = len({match.group(1) for text in steps for match in _ACTION_RE.finditer(text)})
    refs = _count_refs(steps + rubric)
    score = 0
    score += 3 if has_format else 0
    score += 2 if minutes_ok else 0
    score += 3 if action_count >= 3 else action_count
    score += 2 if refs >= 3 else 0
    return min(score, 10), f"format={has_format}, expected_minutes={minutes}, 행동동사 {min(action_count, 3)}, p.참조 {refs}"


def _score_notes(result: dict[str, object]) -> tuple[int, str]:
    blocks = _dict_list(result.get("note_blocks"))
    anchored = sum(1 for block in blocks if _count_refs(_str_list(block.get("bullets"))) > 0)
    long_bullets = sum(len(bullet) >= 30 for block in blocks for bullet in _str_list(block.get("bullets")))
    score = min(15, anchored * 4 + min(long_bullets, 3))
    return score, f"p.참조 {anchored}, 긴 bullet {long_bullets}"


def _score_references(result: dict[str, object]) -> tuple[int, str]:
    values = _reference_values(result)
    used = _extract_ref_pages(values)
    whitelist = set(_int_list(result.get("reference_pages")))
    note_pages = _extract_ref_pages([bullet for block in _dict_list(result.get("note_blocks")) for bullet in _str_list(block.get("bullets"))])
    invalid = sorted(used - whitelist) if whitelist else []
    if invalid:
        return 6, f"미검증 페이지 {invalid}"
    if len(note_pages) >= 3 and len(used) >= 3:
        return 10, f"암기노트 {len(note_pages)}, 전체 p.참조 {len(used)}"
    return 7, f"암기노트 {len(note_pages)}, 전체 p.참조 {len(used)}"


def _score_slides(payload: dict[str, object], result: dict[str, object]) -> tuple[int, str]:
    slides = _dict_list(result.get("slides"))
    iframe = "\n".join(str(slide.get("iframe_html", "")) for slide in slides)
    document_count = sum("<!DOCTYPE html>" in str(slide.get("iframe_html", "")) for slide in slides)
    score = 0 if not slides else 4 + round(4 * document_count / len(slides))
    if "code-card" in iframe and "tok-keyword" in iframe:
        score += 2
    return min(score, 10), f"slides={len(slides)}, doctype={document_count}, code_theme={'code-card' in iframe}"


def _score_visual_gates(payload: dict[str, object], result: dict[str, object]) -> tuple[int, str]:
    iframe_by_idx = {int(slide.get("slide_idx", idx)): str(slide.get("iframe_html", "")) for idx, slide in enumerate(_dict_list(result.get("slides")))}
    missing: list[str] = []
    if "rendered-chart" not in iframe_by_idx.get(0, ""):
        missing.append("slide0 차트 렌더")
    if "mermaid-fallback" not in iframe_by_idx.get(1, "") and "<svg" not in iframe_by_idx.get(1, ""):
        missing.append("slide1 다이어그램 렌더")
    if "code-card" not in iframe_by_idx.get(2, "") or "formula" not in iframe_by_idx.get(2, ""):
        missing.append("slide2 코드/수식 렌더")
    if "flow-strip" not in iframe_by_idx.get(3, ""):
        missing.append("slide3 흐름 시각화")
    if "<details" not in iframe_by_idx.get(4, ""):
        missing.append("slide4 인터랙션")
    raw = any("chart-box" in value or '<pre class="mermaid"' in value or "<pre><code>" in value for value in iframe_by_idx.values())
    if raw:
        missing.append("렌더되지 않은 raw 시각 블록")
    if not missing:
        return 10, "PASS"
    return max(0, 10 - len(missing) * 2), ", ".join(missing)


def _score_lesson_contract(result: dict[str, object]) -> tuple[int, str]:
    assignment = _dict(result.get("assignment"))
    missing: list[str] = []
    if not _dict_list(result.get("slides")):
        missing.append("슬라이드")
    if not _dict_list(result.get("voice_scripts")):
        missing.append("음성대본")
    if not _dict_list(result.get("note_blocks")):
        missing.append("핵심노트")
    if not assignment.get("assignment_format"):
        missing.append("과제 형식")
    if missing:
        return max(0, 10 - len(missing) * 2), ", ".join(missing)
    return 10, "PASS"


def _score(payload: dict[str, object], result: dict[str, object], parse_error: str, warnings: list[str]) -> dict[str, object]:
    failures: list[str] = []
    if parse_error:
        failures.append("파싱 실패")
    if warnings:
        failures.append("후처리 경고")
    total = 0
    for score, _note in (
        _score_slides(payload, result),
        _score_visual_gates(payload, result),
        _score_lesson_contract(result),
        _score_assignment(result),
        _score_notes(result),
        _score_references(result),
    ):
        total += score
    return {"total": total, "pass": not failures and total >= 55, "critical_failures": failures}


def _reference_values(result: dict[str, object]) -> list[str]:
    values: list[str] = []
    for block in _dict_list(result.get("note_blocks")):
        values.extend(_str_list(block.get("bullets")))
    values.extend(str(item.get("script_text", "")) for item in _dict_list(result.get("voice_scripts")))
    assignment = _dict(result.get("assignment"))
    values.extend(_str_list(assignment.get("steps")))
    values.extend(_str_list(assignment.get("rubric")))
    return values


def _dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _dict_list(value: object) -> list[dict[str, object]]:
    return [item for item in value] if isinstance(value, list) and all(isinstance(item, dict) for item in value) else []


def _str_list(value: object) -> list[str]:
    return [item for item in value] if isinstance(value, list) and all(isinstance(item, str) for item in value) else []


def _int_list(value: object) -> list[int]:
    return [item for item in value] if isinstance(value, list) and all(isinstance(item, int) for item in value) else []
