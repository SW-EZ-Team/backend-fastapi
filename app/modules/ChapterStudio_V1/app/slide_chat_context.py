from __future__ import annotations

from app.modules.ChapterStudio_V1.app.demo_pedagogy import note_blocks, voice_scripts
from app.modules.ChapterStudio_V1.app.demo_request import DemoGenerationInput
from app.modules.ChapterStudio_V1.app.slide_chat_types import SlideChatContext, SlideChatRequest
from app.modules.ChapterStudio_V1.app.study_templates import SlideFrame, select_template
from app.modules.ChapterStudio_V1.app.tutor_blueprints import blueprint_for


def build_demo_chat_context(req: SlideChatRequest) -> SlideChatContext:
    """데모 입력을 운영 DB 컨텍스트와 같은 모양으로 압축한다."""
    data = DemoGenerationInput(topic=req.topic, teacher=req.teacher, tone=req.tone, pace=req.pace,
                               tutor_depth=req.tutor_depth, socratic=req.socratic,
                               audience_level=req.audience_level, weak_points=req.weak_points)
    selected = select_template(req.template, req.topic)
    frames = selected.frames
    frame = frames[min(req.slide_idx, len(frames) - 1)]
    blueprint = blueprint_for(selected.key)
    voices = voice_scripts(data, frames, blueprint)
    notes = note_blocks(data, selected.note_blocks, blueprint)
    return SlideChatContext(
        lesson_id=req.lesson_id,
        slide_id=req.slide_id,
        slide_idx=frame.slide_idx,
        slide_title=f"{req.topic} · {frame.role}",
        slide_role=frame.role,
        category=frame.category,
        focus=_focus(req, frame),
        checkpoint=_checkpoint(req, frame),
        voice_script=voices[frame.slide_idx]["script_text"],
        note_bullets=notes[0]["bullets"],
        weak_points=req.weak_points or "아직 표시되지 않은 취약점",
        tutor_style=_tutor_style(req),
        previous_role=_neighbor_role(frames, frame.slide_idx - 1),
        next_role=_neighbor_role(frames, frame.slide_idx + 1),
    )


def _neighbor_role(frames: tuple[SlideFrame, ...], index: int) -> str:
    if 0 <= index < len(frames):
        return frames[index].role
    return "없음"


def _focus(req: SlideChatRequest, frame: SlideFrame) -> str:
    return f"{frame.role} · {req.tutor_depth} 깊이"


def _checkpoint(req: SlideChatRequest, frame: SlideFrame) -> str:
    required = ", ".join(frame.must_have[:2])
    return f"{req.topic}에서 {required} 항목을 설명할 수 있는가?"


def _tutor_style(req: SlideChatRequest) -> str:
    pace = "천천히" if req.pace < 45 else "속도감 있게"
    depth = "예외까지" if req.tutor_depth >= 70 else "핵심 먼저"
    question = "질문으로 유도" if req.socratic >= 60 else "정답 먼저"
    return f"{req.teacher} · {pace} · {depth} · {question}"
