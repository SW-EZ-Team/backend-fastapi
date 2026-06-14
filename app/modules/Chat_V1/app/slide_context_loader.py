"""슬라이드 컨텍스트 DB 조회 모듈 — Chat_V1 전용 원자 모듈.

public.slide 테이블에서 lesson_id(= chapter_id)에 속한 슬라이드를 조회해
Chat_V1 LectureContext 구성에 필요한 SlideContext 목록을 반환한다.

한 가지 책임만 가진다: DB에서 슬라이드를 읽어 SlideContext 리스트로 변환.

[버그 수정 2026-06-04]
public.slide.content는 ChapterStudio가 저장한 raw iframe HTML이다.
HTML을 그대로 proimpt에 넣으면 scope_guard의 build_lecture_keywords가
"div", "section", "class" 같은 HTML 태그/속성 이름을 강의 키워드로 인식한다.
그 결과 모델이 올바른 강의 근거 답변을 생성해도 apply_hallucination_guard가
키워드 불일치로 오판해 범위 밖 안내문(SCOPE_NOTICE)을 잘못 덧붙인다.
→ _html_to_text()로 HTML에서 가시 텍스트만 추출한 뒤 슬라이드 컨텍스트를 구성한다.
"""
from __future__ import annotations

import html as _html_module
import logging
import re
from html.parser import HTMLParser

from app.modules.Chat_V1.app.schemas import SlideContext
from common.db import get_connection

_LOG = logging.getLogger(__name__)

# 슬라이드 텍스트를 프롬프트에 삽입할 때의 최대 길이 (프롬프트 과부하 방지)
_SLIDE_CONTENT_MAX_LEN = 800

# iframe srcdoc 속성에서 내부 HTML을 추출하는 패턴
_SRCDOC_RE = re.compile(r"""\bsrcdoc\s*=\s*(["'])(.*?)\1""", re.IGNORECASE | re.DOTALL)
# 연속 공백을 단일 공백으로 압축하기 위한 패턴
_SPACE_RE = re.compile(r"\s+")


class _VisibleTextParser(HTMLParser):
    """HTML 조각에서 화면에 보이는 텍스트만 수집한다.

    script·style 블록은 숨겨진 콘텐츠이므로 제외한다.
    """

    _hidden_tags: frozenset[str] = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._hidden_depth: int = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._hidden_tags:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._hidden_tags and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth and data.strip():
            self._parts.append(data)

    def visible_text(self) -> str:
        """수집한 텍스트 조각을 공백으로 연결하고 정규화해 반환한다."""
        raw = " ".join(self._parts)
        return _SPACE_RE.sub(" ", raw).strip()


def _extract_srcdoc(markup: str) -> str | None:
    """srcdoc 속성 값을 추출한다. 없으면 None을 반환한다."""
    match = _SRCDOC_RE.search(markup)
    if not match:
        return None
    inner = _html_module.unescape(match.group(2)).strip()
    return inner or None


def _html_to_text(raw: str) -> str:
    """HTML 문자열에서 가시 텍스트만 추출한다.

    public.slide.content는 iframe srcdoc 형식일 수 있다.
    srcdoc 속성이 있으면 내부 HTML을 먼저 꺼내고, 그 HTML에서 텍스트를 파싱한다.
    srcdoc 없이 일반 HTML이면 그대로 파싱한다.
    """
    html_fragment = _extract_srcdoc(raw) or raw
    unescaped = _html_module.unescape(html_fragment)
    parser = _VisibleTextParser()
    parser.feed(unescaped)
    parser.close()
    return parser.visible_text()


async def load_slides(
    lesson_id: str,
    current_slide_idx: int | None,
) -> list[SlideContext]:
    """public.slide에서 lesson_id(= chapter_id) 슬라이드를 조회한다.

    current_slide_idx가 있으면 해당 슬라이드를 목록 맨 앞에 배치해 모델이
    현재 슬라이드를 우선 참조하도록 유도한다.
    DB 오류나 슬라이드 없음 시 빈 목록을 반환해 호출부가 폴백하게 한다.
    """
    rows = await _fetch_rows(lesson_id)
    if not rows:
        return []

    slides = _rows_to_slide_contexts(rows)
    if not slides:
        return []

    return _prioritize_current(slides, current_slide_idx)


async def _fetch_rows(lesson_id: str) -> list[dict[str, object]]:
    """public.slide에서 lesson_id에 속한 행을 slide_idx 순으로 조회한다.

    asyncpg Record는 dict()로 변환해 반환한다. 타입체커가 Mapping[str, object]로
    안전하게 추론할 수 있도록 워크어라운드 없이 근본적으로 변환한다.
    """
    try:
        async with get_connection() as conn:
            rows = await conn.fetch(
                "SELECT slide_idx, title, content "
                "FROM public.slide "
                "WHERE chapter_id = $1 "
                "ORDER BY slide_idx ASC",
                lesson_id,
            )
        # asyncpg Record → dict 변환으로 타입체커가 키 접근을 안전하게 추론한다
        return [dict(row) for row in rows]
    except Exception as exc:
        _LOG.warning(
            "[slide-loader] public.slide 조회 실패 — lesson_id=%s, error=%s",
            lesson_id,
            exc,
        )
        return []


def _rows_to_slide_contexts(rows: list[dict[str, object]]) -> list[SlideContext]:
    """DB 행 목록을 SlideContext 리스트로 변환한다.

    title이 없으면 슬라이드 번호로 대체하고, HTML 추출 후 텍스트가 없으면
    해당 슬라이드를 건너뛴다 — min_length=1 계약을 보장한다.

    [핵심] content 컬럼은 raw iframe HTML이므로 _html_to_text()로 가시 텍스트만
    추출한다. 이렇게 해야 scope_guard가 실제 강의 용어를 키워드로 인식한다.
    """
    slides: list[SlideContext] = []
    for row in rows:
        raw_title = row.get("title")
        raw_content = row.get("content")
        raw_idx = row.get("slide_idx")
        # 기본값 처리 — DB 컬럼이 NULL일 수 있으므로 str 타입만 사용한다
        title = (raw_title if isinstance(raw_title, str) else "").strip()
        html_content = (raw_content if isinstance(raw_content, str) else "").strip()
        slide_idx: int = raw_idx if isinstance(raw_idx, int) else 0
        if not title:
            title = f"슬라이드 {slide_idx + 1}"
        # HTML에서 가시 텍스트 추출 — raw HTML을 그대로 쓰면 태그명이 키워드로 오염된다
        content = _html_to_text(html_content) if html_content else ""
        if not content:
            # 텍스트 추출에 실패하면 raw HTML을 그대로 저장하지 않고 건너뛴다
            _LOG.debug(
                "[slide-loader] 슬라이드 텍스트 추출 실패 — lesson_id 미상, slide_idx=%s",
                slide_idx,
            )
            continue
        slides.append(
            SlideContext(
                slide_idx=slide_idx,
                title=title,
                content=content[:_SLIDE_CONTENT_MAX_LEN],
            )
        )
    return slides


def _prioritize_current(
    slides: list[SlideContext],
    current_slide_idx: int | None,
) -> list[SlideContext]:
    """현재 슬라이드를 목록 앞에 배치해 모델이 현재 위치를 우선 참조하게 한다."""
    if current_slide_idx is None:
        return slides
    current = [s for s in slides if s.slide_idx == current_slide_idx]
    others = [s for s in slides if s.slide_idx != current_slide_idx]
    return current + others
