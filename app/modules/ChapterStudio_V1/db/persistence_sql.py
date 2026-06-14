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
        "VALUES ($1,$2,'done','persist_chapter_state',5,5,100,$3,$4,$5::jsonb,NULL,NOW(),NOW()) "
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


def public_delete_assignment_sql() -> str:
    """재생성 시 같은 chapter의 과제를 비워 멱등 재삽입을 보장한다.

    public.assignment는 id만 PK라 매 생성마다 새 asg id가 만들어진다.
    chapter당 과제 1개 규칙을 유지하려면 slide와 동일하게 chapter_id 기준으로 선삭제한다.
    """
    return "DELETE FROM public.assignment WHERE chapter_id = $1"


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


def public_assignment_sql() -> str:
    """Spring Assignment 엔티티가 읽는 public.assignment 저장 쿼리다.

    chapter_id 선삭제가 재생성 멱등성을 책임지고, ON CONFLICT (id)는 PK 충돌 안전망이다.
    status='active'/total_questions는 NOT NULL이라 항상 값을 채운다.
    """
    return (
        "INSERT INTO public.assignment "
        "(id, user_id, course_id, chapter_id, status, title, description, "
        "total_questions, questions, created_at, updated_at) "
        "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW(), NOW()) "
        "ON CONFLICT (id) DO UPDATE SET "
        "user_id = EXCLUDED.user_id, "
        "course_id = EXCLUDED.course_id, "
        "chapter_id = EXCLUDED.chapter_id, "
        "status = EXCLUDED.status, "
        "title = EXCLUDED.title, "
        "description = EXCLUDED.description, "
        "total_questions = EXCLUDED.total_questions, "
        "questions = EXCLUDED.questions, "
        "updated_at = NOW()"
    )


def running_status_sql(schema: str) -> str:
    """생성 시작 시점에 진행중(running) 상태를 lesson_generation_status에 남기는 upsert 쿼리다.

    조용한 실패로 0행만 남던 문제를 완화한다 — 중간에 죽어도 'running' 행이 남아
    진행률 0% 고정과 진단 불가 상태를 막는다. result_summary/generation_model은 건드리지 않는다.
    """
    return (
        f"INSERT INTO {_table(schema, 'lesson_generation_status')} "
        "(lesson_id, tutoring_id, status, current_node, completed_nodes, total_nodes, "
        "progress_percent, chapter_id, generation_model, result_summary, error_message, updated_at, completed_at) "
        "VALUES ($1,$2,'running','generate_chapter_state',0,5,0,$3,NULL,'{}'::jsonb,NULL,NOW(),NULL) "
        "ON CONFLICT (lesson_id) DO UPDATE SET "
        "tutoring_id = EXCLUDED.tutoring_id, "
        "status = EXCLUDED.status, "
        "current_node = EXCLUDED.current_node, "
        "completed_nodes = EXCLUDED.completed_nodes, "
        "total_nodes = EXCLUDED.total_nodes, "
        "progress_percent = EXCLUDED.progress_percent, "
        "chapter_id = EXCLUDED.chapter_id, "
        "error_message = NULL, "
        "updated_at = NOW(), "
        "completed_at = NULL"
    )


def progress_status_sql(schema: str) -> str:
    """그래프 노드 완료 시점마다 진행률을 lesson_generation_status에 남기는 upsert 쿼리다.

    Spring/프론트가 챕터 단위(AVAILABLE) 신호만 보던 것을 노드 단위 진행률로 세분화한다.
    스테일 콜백 가드: 이미 종결된 행(status='done'/'failed')은 되돌리지 않는다 —
    완료 직후 도착한 늦은 노드 진행률 기록이 done→running 역행을 일으켜 프론트 폴링이
    영원히 running에 갇히는 것을 막는다. 재생성은 running_status_sql(mark_chapter_running)이
    먼저 행을 running으로 되돌리므로 이 가드와 충돌하지 않는다.
    result_summary/generation_model은 건드리지 않는다.
    """
    table = _table(schema, "lesson_generation_status")
    return (
        f"INSERT INTO {table} "
        "(lesson_id, tutoring_id, status, current_node, completed_nodes, total_nodes, "
        "progress_percent, chapter_id, generation_model, result_summary, error_message, updated_at, completed_at) "
        "VALUES ($1,$2,'running',$3,$4,$5,$6,$7,NULL,'{}'::jsonb,NULL,NOW(),NULL) "
        "ON CONFLICT (lesson_id) DO UPDATE SET "
        "tutoring_id = EXCLUDED.tutoring_id, "
        "status = EXCLUDED.status, "
        "current_node = EXCLUDED.current_node, "
        "completed_nodes = EXCLUDED.completed_nodes, "
        "total_nodes = EXCLUDED.total_nodes, "
        "progress_percent = EXCLUDED.progress_percent, "
        "chapter_id = EXCLUDED.chapter_id, "
        "error_message = NULL, "
        "updated_at = NOW(), "
        "completed_at = NULL "
        f"WHERE {table}.status NOT IN ('done', 'failed')"
    )


def failure_status_sql(schema: str) -> str:
    """실패 상태를 lesson_generation_status에 남기는 upsert 쿼리다."""
    return (
        f"INSERT INTO {_table(schema, 'lesson_generation_status')} "
        "(lesson_id, tutoring_id, status, current_node, completed_nodes, total_nodes, "
        "progress_percent, chapter_id, generation_model, result_summary, error_message, updated_at, completed_at) "
        "VALUES ($1,$2,'failed',$3,0,5,0,$4,NULL,$5::jsonb,$6,NOW(),NOW()) "
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


def audio_pending_status_sql(schema: str) -> str:
    """강의는 완료됐지만 음성 백필 재시도가 필요한 상태를 result_summary에 합친다."""
    return (
        f"UPDATE {_table(schema, 'lesson_generation_status')} SET "
        "current_node = 'audio_backfill', "
        "result_summary = COALESCE(result_summary, '{}'::jsonb) "
        "|| jsonb_build_object('audio_backfill', $2::jsonb), "
        "error_message = $3, "
        "updated_at = NOW() "
        "WHERE lesson_id = $1"
    )


def save_reference_book_context_sql(schema: str) -> str:
    """OCR 완료 후 참고도서 컨텍스트를 lesson_generation_status.generation_context JSONB에 저장한다.

    generation_context JSONB에 reference_book_context 키만 병합(upsert)하고,
    나머지 필드(depth, tone 등)는 건드리지 않는다.
    lesson_generation_status 행이 없으면 tutoring_id='' 로 신규 생성한다.
    """
    return (
        f"INSERT INTO {_table(schema, 'lesson_generation_status')} "
        "(lesson_id, tutoring_id, status, current_node, completed_nodes, total_nodes, "
        "progress_percent, chapter_id, generation_model, result_summary, error_message, "
        "generation_context, updated_at, completed_at) "
        "VALUES ($1, '', 'pending', 'ocr_done', 0, 3, 0, '', NULL, '{}'::jsonb, NULL, "
        "$2::jsonb, NOW(), NULL) "
        "ON CONFLICT (lesson_id) DO UPDATE SET "
        "generation_context = COALESCE("
        f"    {_table(schema, 'lesson_generation_status')}.generation_context, '{{}}' ::jsonb"
        ") || jsonb_build_object('reference_book_context', ($2::jsonb)->'reference_book_context'), "
        "updated_at = NOW()"
    )


def generation_status_select_sql(schema: str) -> str:
    """프론트 진행률 표시용 lesson_generation_status 단건 조회 쿼리다.

    Spring 프록시(GET /tutoring/{courseId}/lessons/{chapterId}/generation-status)가
    폴링하며, 노드 단위 진행률(progress_percent)을 사용자 대기 화면에 노출한다.
    """
    return (
        "SELECT status, current_node, completed_nodes, total_nodes, "
        "progress_percent, error_message "
        f"FROM {_table(schema, 'lesson_generation_status')} "
        "WHERE lesson_id = $1"
    )


def _table(schema: str, name: str) -> str:
    return f"{schema}.{name}"
