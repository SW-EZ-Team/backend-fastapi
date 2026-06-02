from __future__ import annotations

import re
from dataclasses import dataclass

from app.modules.ChapterStudio_V1.pipeline.cjk_text import CJK_RE, strip_cjk

_TOKEN_RE = re.compile(r"[0-9A-Za-z가-힣]+")
_SENTENCE_RE = re.compile(r"[^.!?。！？]+[.!?。！？]?")
_QUESTION_RE = re.compile(r"(?P<token>[가-힣]*(?:까요|나요|을까|ㄹ까|까))(?P<tail>[.\s]|$)")
_SPELLING_FIXES: dict[str, str] = {
    "절대값": "절댓값",
    "최대값": "최댓값",
    "최소값": "최솟값",
}
_QUESTION_EXCLUDE_SUFFIXES = ("니까", "으니까")


@dataclass(frozen=True)
class TextIssue:
    kind: str
    message: str
    fragment: str
    start: int
    end: int
    suggestion: str = ""


@dataclass(frozen=True)
class TextIssueBucket:
    source: str
    index: int
    issues: list[TextIssue]


@dataclass(frozen=True)
class DuplicateIntroGroup:
    members: list[str]
    intro: str
    similarity: float


@dataclass(frozen=True)
class QualityInspectionReport:
    items: list[TextIssueBucket]
    duplicate_intro_groups: list[DuplicateIntroGroup]

    @property
    def total_issues(self) -> int:
        return sum(len(item.issues) for item in self.items)


def inspect_text(text: str) -> list[TextIssue]:
    """한 텍스트 안의 결정적 교정 후보를 규칙 기반으로 찾는다."""
    issues: list[TextIssue] = []
    issues.extend(_cjk_issues(text))
    issues.extend(_spelling_issues(text))
    issues.extend(_missing_question_mark_issues(text))
    return issues


def apply_spelling_fixes(text: str) -> str:
    """LLM 교정 여부와 무관하게 확정 표기만 규칙 기반으로 치환한다."""
    fixed = text
    for wrong, right in _SPELLING_FIXES.items():
        fixed = re.sub(re.escape(wrong), right, fixed)
    return fixed


def inspect_lesson(
    voice_scripts: list[str],
    slide_narrations: list[str],
) -> QualityInspectionReport:
    """교정 전 품질 문제를 기록한다. 이 리포트는 차단하지 않고 로그용으로만 쓴다."""
    entries = _entries(voice_scripts, slide_narrations)
    buckets = [
        TextIssueBucket(source=source, index=index, issues=inspect_text(text))
        for source, index, text in entries
    ]
    duplicate_groups = _duplicate_intro_groups(entries)
    if duplicate_groups:
        buckets = _with_duplicate_issues(buckets, duplicate_groups)
    return QualityInspectionReport(items=buckets, duplicate_intro_groups=duplicate_groups)


def _cjk_issues(text: str) -> list[TextIssue]:
    return [
        TextIssue("cjk", "한국어 강의 텍스트에 한자·가나 문자가 섞여 있다.", match.group(), match.start(), match.end())
        for match in CJK_RE.finditer(text)
    ]


def _spelling_issues(text: str) -> list[TextIssue]:
    issues: list[TextIssue] = []
    for wrong, right in _SPELLING_FIXES.items():
        for match in re.finditer(re.escape(wrong), text):
            issues.append(TextIssue("spelling", "표준어 표기가 아니다.", wrong, match.start(), match.end(), right))
    return issues


def _missing_question_mark_issues(text: str) -> list[TextIssue]:
    issues: list[TextIssue] = []
    for match in _QUESTION_RE.finditer(text):
        token = match.group("token")
        if token.endswith(_QUESTION_EXCLUDE_SUFFIXES):
            continue
        issues.append(
            TextIssue(
                "missing_question_mark",
                "의문 종결어미 뒤에 물음표가 없다.",
                token,
                match.start("token"),
                match.end("token"),
                f"{token}?",
            )
        )
    return issues


def _entries(voice_scripts: list[str], slide_narrations: list[str]) -> list[tuple[str, int, str]]:
    voices = [("voice_script", index, text) for index, text in enumerate(voice_scripts)]
    slides = [("slide_narration", index, text) for index, text in enumerate(slide_narrations)]
    return voices + slides


def _duplicate_intro_groups(entries: list[tuple[str, int, str]]) -> list[DuplicateIntroGroup]:
    intros = [(source, index, _intro(text)) for source, index, text in entries if _intro(text)]
    seen: set[int] = set()
    groups: list[DuplicateIntroGroup] = []
    for left, (source, index, intro) in enumerate(intros):
        if left in seen:
            continue
        matches = [(source, index, intro, 1.0)]
        for right in range(left + 1, len(intros)):
            other_source, other_index, other_intro = intros[right]
            score = _intro_similarity(intro, other_intro)
            if score >= 0.72 or _prefix_ratio(intro, other_intro) >= 0.55:
                seen.add(right)
                matches.append((other_source, other_index, other_intro, score))
        if len(matches) > 1:
            seen.add(left)
            groups.append(_group_from_matches(matches))
    return groups


def _with_duplicate_issues(
    buckets: list[TextIssueBucket],
    groups: list[DuplicateIntroGroup],
) -> list[TextIssueBucket]:
    issue_map = {(bucket.source, bucket.index): list(bucket.issues) for bucket in buckets}
    for group in groups:
        for member in group.members:
            source, raw_index = member.split(":", 1)
            issue_map[(source, int(raw_index))].append(
                TextIssue("duplicate_intro", "도입부가 다른 슬라이드와 과도하게 유사하다.", group.intro, 0, len(group.intro))
            )
    return [TextIssueBucket(bucket.source, bucket.index, issue_map[(bucket.source, bucket.index)]) for bucket in buckets]


def _group_from_matches(matches: list[tuple[str, int, str, float]]) -> DuplicateIntroGroup:
    members = [f"{source}:{index}" for source, index, _, _ in matches]
    score = min(score for _, _, _, score in matches[1:])
    return DuplicateIntroGroup(members=members, intro=matches[0][2], similarity=round(score, 3))


def _intro(text: str) -> str:
    sentences = [part.strip() for part in _SENTENCE_RE.findall(text.strip()) if part.strip()]
    return " ".join(sentences[:2])[:180]


def _intro_similarity(left: str, right: str) -> float:
    left_tokens = set(_TOKEN_RE.findall(left.lower()))
    right_tokens = set(_TOKEN_RE.findall(right.lower()))
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / len(left_tokens | right_tokens)


def _prefix_ratio(left: str, right: str) -> float:
    limit = min(len(left), len(right))
    same = 0
    for idx in range(limit):
        if left[idx] != right[idx]:
            break
        same += 1
    return same / max(1, limit)


__all__ = [
    "DuplicateIntroGroup",
    "QualityInspectionReport",
    "TextIssue",
    "TextIssueBucket",
    "apply_spelling_fixes",
    "inspect_lesson",
    "inspect_text",
    "strip_cjk",
]
