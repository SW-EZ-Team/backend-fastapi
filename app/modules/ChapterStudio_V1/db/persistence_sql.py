from __future__ import annotations


def delete_queue_sql(schema: str) -> str:
    """voice_script에 연결된 대기열을 lesson/chapter 범위로 지운다."""
    return (
        f"DELETE FROM {_table(schema, 'voice_script_queue')} q "
        f"USING {_table(schema, 'voice_script')} v "
        "WHERE q.voice_script_id = v.id "
        "AND (v.lesson_id = $1 OR v.chapter_id = $2)"
    )


def slide_sql(schema: str) -> str:
    """프론트 계약과 기존 V2 컬럼을 함께 채우는 slide 저장 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'slide')} "
        "(id, chapter_id, index, category, html, css, tutoring_id, lesson_id, "
        "slide_idx, title, template_id, iframe_html, semantic_meta, "
        "validation_status, design_version, updated_at) "
        "VALUES ($1,$2,$3,$4,$5,'',$6,$7,$8,$9,$10,$5,$11::jsonb,'ready','v1',NOW())"
    )


def quiz_sql(schema: str) -> str:
    """quiz 저장 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'quiz')} "
        "(id, chapter_id, question, choices, answer_idx, explanation, depth, "
        "tutoring_id, lesson_id, quiz_idx, difficulty, source_slide_ids) "
        "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10,$7,$11::jsonb)"
    )


def note_sql(schema: str) -> str:
    """핵심 노트 저장 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'note')} "
        "(id, chapter_id, html, tutoring_id, lesson_id, summary_json, updated_at) "
        "VALUES ($1,$2,$3,$4,$5,$6::jsonb,NOW())"
    )


def assignment_sql(schema: str) -> str:
    """과제 저장 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'assignment')} "
        "(id, chapter_id, prompt, criteria, expected_minutes, tutoring_id, lesson_id, "
        "title, expected_input_type, allowed_extensions, display_html) "
        "VALUES ($1,$2,$3,$4::jsonb,$5,$6,$7,$8,$9,$10::jsonb,$11)"
    )


def voice_sql(schema: str) -> str:
    """음성 대본 저장 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'voice_script')} "
        "(id, chapter_id, slide_index, text, duration_hint_sec, audio_url, "
        "tutoring_id, lesson_id, slide_id, script_text, tone) "
        "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$4,'default')"
    )


def queue_sql(schema: str) -> str:
    """TTS 워커가 처리할 pending voice_script_queue 저장 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'voice_script_queue')} "
        "(id, voice_script_id, status) "
        "VALUES ($1,$2,'pending')"
    )


def status_sql(schema: str) -> str:
    """lesson_generation_status 완료 상태 upsert 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'lesson_generation_status')} "
        "(lesson_id, tutoring_id, status, current_node, completed_nodes, total_nodes, "
        "progress_percent, chapter_id, generation_model, result_summary, error_message, updated_at, completed_at) "
        "VALUES ($1,$2,'done','persist_chapter_state',3,3,100,$3,$4,$5::jsonb,NULL,NOW(),NOW()) "
        "ON CONFLICT (lesson_id) DO UPDATE SET "
        "status = EXCLUDED.status, "
        "current_node = EXCLUDED.current_node, "
        "completed_nodes = EXCLUDED.completed_nodes, "
        "total_nodes = EXCLUDED.total_nodes, "
        "progress_percent = EXCLUDED.progress_percent, "
        "chapter_id = EXCLUDED.chapter_id, "
        "generation_model = EXCLUDED.generation_model, "
        "result_summary = EXCLUDED.result_summary, "
        "error_message = NULL, "
        "updated_at = NOW(), "
        "completed_at = NOW()"
    )


def public_delete_quiz_sql() -> str:
    """public.slide FK 삭제 전에 같은 chapter의 quiz를 제거한다."""
    return "DELETE FROM public.quiz WHERE chapter_id = $1"


def public_delete_note_sql() -> str:
    """재생성 중복 방지를 위해 FastAPI 자동 노트만 제거한다."""
    return (
        "DELETE FROM public.note "
        "WHERE user_id = $1 AND course_id = $2 AND chapter_id = $3 AND type = $4"
    )


def public_delete_slide_sql() -> str:
    """public.quiz 제거 뒤 같은 chapter의 slide를 재삽입 가능하게 비운다."""
    return "DELETE FROM public.slide WHERE chapter_id = $1"


def public_slide_sql() -> str:
    """Spring Slide 엔티티가 읽는 public.slide 저장 쿼리다."""
    return (
        "INSERT INTO public.slide "
        "(id, chapter_id, slide_idx, title, content, audio_url, duration_sec) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
        "ON CONFLICT (chapter_id, slide_idx) DO UPDATE SET "
        "id = EXCLUDED.id, "
        "title = EXCLUDED.title, "
        "content = EXCLUDED.content, "
        "audio_url = EXCLUDED.audio_url, "
        "duration_sec = EXCLUDED.duration_sec"
    )


def public_quiz_sql() -> str:
    """Spring Quiz 엔티티가 읽는 public.quiz 저장 쿼리다."""
    return (
        "INSERT INTO public.quiz "
        "(id, chapter_id, quiz_idx, question_text, options, correct_option, explanation, slide_id) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8) "
        "ON CONFLICT (slide_id) DO UPDATE SET "
        "id = EXCLUDED.id, "
        "chapter_id = EXCLUDED.chapter_id, "
        "quiz_idx = EXCLUDED.quiz_idx, "
        "question_text = EXCLUDED.question_text, "
        "options = EXCLUDED.options, "
        "correct_option = EXCLUDED.correct_option, "
        "explanation = EXCLUDED.explanation"
    )


def public_note_sql() -> str:
    """Spring Note 엔티티가 읽는 public.note 저장 쿼리다."""
    return (
        "INSERT INTO public.note "
        "(id, user_id, course_id, chapter_id, type, title, content) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7) "
        "ON CONFLICT (id) DO UPDATE SET "
        "title = EXCLUDED.title, "
        "content = EXCLUDED.content, "
        "updated_at = NOW()"
    )


def failure_status_sql(schema: str) -> str:
    """실패 상태를 lesson_generation_status에 남기는 upsert 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'lesson_generation_status')} "
        "(lesson_id, tutoring_id, status, current_node, completed_nodes, total_nodes, "
        "progress_percent, chapter_id, generation_model, result_summary, error_message, updated_at, completed_at) "
        "VALUES ($1,$2,'failed',$3,0,3,0,$4,NULL,$5::jsonb,$6,NOW(),NOW()) "
        "ON CONFLICT (lesson_id) DO UPDATE SET "
        "status = EXCLUDED.status, "
        "current_node = EXCLUDED.current_node, "
        "completed_nodes = EXCLUDED.completed_nodes, "
        "total_nodes = EXCLUDED.total_nodes, "
        "progress_percent = EXCLUDED.progress_percent, "
        "chapter_id = EXCLUDED.chapter_id, "
        "generation_model = NULL, "
        "result_summary = EXCLUDED.result_summary, "
        "error_message = EXCLUDED.error_message, "
        "updated_at = NOW(), "
        "completed_at = NOW()"
    )


def _table(schema: str, name: str) -> str:
    return f"{schema}.{name}"
