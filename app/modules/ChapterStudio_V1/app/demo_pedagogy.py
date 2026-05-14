from __future__ import annotations

from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.demo_types import DemoAssignment, DemoNoteBlock, DemoVoiceScript
from app.modules.ChapterStudio_V1.app.reference_books.prompt_blocks import (
    reference_assignment_step,
    reference_note_bullet,
    reference_voice_sentence,
)
from app.modules.ChapterStudio_V1.app.template_types import SlideFrame
from app.modules.ChapterStudio_V1.app.tutor_blueprints import TutorBlueprint


def lesson_points(data: DemoGenerationInput, blueprint: TutorBlueprint) -> tuple[str, str, str]:
    """첫 슬라이드에 들어갈 과외식 핵심 문장을 만든다."""
    return (
        f"{data.topic}{_josa(data.topic, '은', '는')} {blueprint.background}",
        f"오늘은 {blueprint.lens} 관점으로 읽는다.",
        f"빠른 학습 순서: {blueprint.fast_route}",
    )


def note_blocks(
    data: DemoGenerationInput, headings: tuple[str, ...], blueprint: TutorBlueprint
) -> list[DemoNoteBlock]:
    """핵심노트를 책 요약이 아니라 과외 복습 블록으로 만든다."""
    return [
        {"heading": heading, "bullets": _note_bullets(data, heading, blueprint, idx)}
        for idx, heading in enumerate(headings[:4])
    ]


def assignment(data: DemoGenerationInput, blueprint: TutorBlueprint) -> DemoAssignment:
    """20분 안에 배운 관점을 바로 전이시키는 과제를 만든다."""
    steps = [
        f"{blueprint.lens} 관점으로 핵심 문장 2개를 쓴다.",
        f"{blueprint.transfer_question}에 대한 짧은 답을 만든다.",
        f"헷갈린 지점을 {blueprint.pitfall} 문장과 연결해 고친다.",
    ]
    reference_step = reference_assignment_step(data.reference_book_context)
    if reference_step:
        steps.append(reference_step)
    return {
        "title": f"{data.topic} 20분 과외 복습 과제",
        "assignment_format": "짧은 서술형 복습지 + 근거 표시",
        "expected_minutes": 20,
        "steps": steps,
        "rubric": ["관점 정확성", "사례 전이", f"{data.depth} 깊이에서의 한계 인식"],
    }


def voice_scripts(
    data: DemoGenerationInput, frames: tuple[SlideFrame, ...], blueprint: TutorBlueprint
) -> list[DemoVoiceScript]:
    """튜터 성향과 슬라이드 역할에 맞춘 음성대본을 만든다."""
    return [
        {"slide_idx": frame.slide_idx, "script_text": _voice_line(data, frame, blueprint)}
        for frame in frames
    ]


def _note_bullets(
    data: DemoGenerationInput, heading: str, blueprint: TutorBlueprint, index: int
) -> list[str]:
    weak = data.weak_points or "아직 표시되지 않은 취약점"
    bullets = [
        _note_core(data, heading, blueprint),
        f"과외 관점: {blueprint.mental_model}",
        f"주의할 함정: {blueprint.pitfall}",
        f"내 취약점 연결: {weak}",
    ]
    reference_bullet = reference_note_bullet(data.reference_book_context, index)
    if reference_bullet:
        bullets.append(reference_bullet)
    return bullets


def _note_core(data: DemoGenerationInput, heading: str, blueprint: TutorBlueprint) -> str:
    if any(word in heading for word in ("이유", "철학", "관점", "배경", "맥락")):
        return f"{data.topic}{_josa(data.topic, '을', '를')} 배우는 이유: {blueprint.philosophy}"
    if any(word in heading for word in ("핵심", "용어", "구조", "모델", "공식")):
        return f"머리에 남길 모델: {blueprint.mental_model}"
    if any(word in heading for word in ("오해", "한계", "논쟁", "주의", "반례")):
        return f"틀리기 쉬운 지점: {blueprint.pitfall}"
    if any(word in heading for word in ("복습", "루틴", "회상", "적용", "영향")):
        return f"빠른 학습 루틴: {blueprint.fast_route}"
    return f"{heading}{_josa(heading, '은', '는')} {blueprint.lens} 관점으로 정리한다."


def _voice_line(
    data: DemoGenerationInput, frame: SlideFrame, blueprint: TutorBlueprint
) -> str:
    style = _teacher_style(data)
    pace = "빠르게 훑지 말고" if data.pace < 45 else "속도감 있게"
    depth = "예외와 한계까지" if data.tutor_depth >= 70 else "핵심만 먼저"
    question = blueprint.transfer_question if data.socratic >= 60 else data.learning_goal
    return (
        f"{frame.slide_idx + 1}번 슬라이드, {frame.role}입니다. {style} "
        f"{pace} {data.topic}{_josa(data.topic, '을', '를')} {blueprint.lens} 관점으로 잡겠습니다. "
        f"여기서는 {depth} 보되, 머리에 남길 문장은 '{blueprint.mental_model}'입니다. "
        f"마지막으로 스스로 물어보세요. {question}"
        f"{reference_voice_sentence(data.reference_book_context, frame.slide_idx)}"
    )


def _teacher_style(data: DemoGenerationInput) -> str:
    if data.teacher == "cat":
        return "친근한 비유로 먼저 긴장을 낮출게요."
    if data.teacher == "fox":
        return "헷갈리는 기준만 날카롭게 집어볼게요."
    if data.teacher == "bear":
        return "천천히 반복해서 확실히 고정해볼게요."
    return "차분하게 질문 하나로 출발하겠습니다."


def _josa(value: str, with_batchim: str, without_batchim: str) -> str:
    stripped = value.strip()
    if not stripped:
        return without_batchim
    code = ord(stripped[-1])
    if 0xAC00 <= code <= 0xD7A3 and (code - 0xAC00) % 28 != 0:
        return with_batchim
    return without_batchim
