from __future__ import annotations

from fastapi.testclient import TestClient

from app.modules.ChapterStudio_V1.app.main import app


def test_demo_page_serves_html() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio")
    assert response.status_code == 200
    assert "ChapterStudio_V1 생성 테스트" in response.text
    assert 'class="quiz-answer"' in response.text
    assert 'srcdoc="${e(s.iframe_html)}"' in response.text
    assert 'idx === q.answer_idx ? "answer" : ""' not in response.text


def test_demo_chat_page_serves_html() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/chat")
    assert response.status_code == 200
    assert "ChapterStudio 슬라이드 채팅" in response.text
    assert "/demo/chapter-studio/chat/stream" in response.text
    assert "Codex OAuth" in response.text


def test_demo_curriculum_page_serves_html() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/curriculum")
    assert response.status_code == 200
    assert "커리큘럼 미리보기" in response.text
    assert "/demo/chapter-studio/curriculum/preview" in response.text


def test_demo_reference_book_page_serves_html() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/reference-book")
    assert response.status_code == 200
    assert "참고도서 OCR 컨텍스트 테스트" in response.text
    assert "/demo/chapter-studio/reference-book/context-preview" in response.text


def test_demo_reference_book_context_preview_returns_page_hits() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/demo/chapter-studio/reference-book/context-preview",
            json={
                "topic": "회귀분석 잔차",
                "source_title": "회귀 교재",
                "ocr_result": {
                    "pages": [
                        {"page_num": 88, "text": "회귀분석에서 잔차는 관측값과 예측값의 차이를 뜻한다."}
                    ],
                    "ocr_model": "paddleocr-ppv4",
                },
            },
        )
    assert response.status_code == 200
    data = response.json()
    assert data["hits"][0]["page"] == 88


def test_demo_stream_returns_sse() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/stream?topic=테스트&slide_count=5&duration_days=60&teacher=cat")
    assert response.status_code == 200
    assert "event: node_complete" in response.text
    assert "event: complete" in response.text


def test_demo_contract_exposes_frontend_fields() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/contract")
    assert response.status_code == 200
    assert "duration_days" in response.text
    assert "tutor_sliders" in response.text
    assert "curriculum_create_path" in response.text


def test_demo_frontend_preview_returns_srcdoc_payload() -> None:
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/frontend-preview?topic=끼워넣기")
    assert response.status_code == 200
    data = response.json()
    assert data["generationStatus"] == "ready"
    assert data["slides"][0]["iframeHtml"].lstrip().startswith("<!DOCTYPE html>")
    assert not data["slides"][0]["iframeHtml"].lstrip().startswith("<iframe")


def test_demo_stream_supports_codex_mode_error(monkeypatch) -> None:
    async def fail_build(data, slide_count: int, engine: str, template: str):
        raise RuntimeError(f"{data.topic} 실패")

    monkeypatch.setattr("app.modules.ChapterStudio_V1.app.routers.demo_chapter_studio.run_demo_agent", fail_build)
    with TestClient(app) as client:
        response = client.get("/demo/chapter-studio/stream?topic=테스트&slide_count=5&engine=codex_cli")
    assert response.status_code == 200
    assert "event: error" in response.text
