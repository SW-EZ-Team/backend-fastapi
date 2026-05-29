# OCR v1 파이프라인 모듈

LangGraph StateGraph 기반의 PDF 문서 처리 파이프라인입니다.
PDF를 입력받아 추출 → 품질 검증 → 후처리 → 청킹 → 임베딩 → 벡터 저장까지 9단계로 처리하고,
RAG 하이브리드 검색(Dense+Sparse+Reranker)을 제공합니다.

---

## 모듈 개요

| 항목 | 내용 |
|---|---|
| 주요 기능 | PDF OCR 인제스트 + Qdrant RAG 하이브리드 검색 |
| 파이프라인 | LangGraph `StateGraph` 9-Stage |
| 기본 OCR 엔진 | Marker (born-digital), MinerU 폴백 |
| 임베딩 모델 | `BAAI/bge-m3` (Dense+Sparse 동시 생성) |
| 리랭커 | `BAAI/bge-reranker-v2-m3` |
| 벡터 저장소 | Qdrant (로컬 또는 원격 서버) |
| 서버 포트 | 8005 (환경변수 `OCR_V1_PORT` 로 변경) |

---

## 아키텍처

```
PDF 입력
  │
  ▼
Stage 1: 페이지 타입 분류 (born-digital / scanned / mixed)
  │
  ▼
Stage 2: OCR 추출 (Marker 엔진)
  │
  ▼
Stage 3: LLM 교정 (선택 — OCR_V1_MARKER_USE_LLM_MODEL 설정 시)
  │
  ▼
Stage 4: 품질 게이트 ─── 실패 ──▶ Stage 5: 폴백 재추출 (MinerU)
  │ (통과)                                │
  └──────────────────────────────────────┘
  │
  ▼
Stage 6: 후처리 (헤더/푸터 제거, 하이픈 복원, 단락 병합, 표/수식 정규화)
  │
  ▼
Stage 7: 섹션 기반 청킹 (tiktoken cl100k_base, 600~1200 토큰)
  │
  ▼
Stage 8: BGE-M3 임베딩 (Dense + Sparse)
  │
  ▼
Stage 9: Qdrant 업서트 (벡터 저장 완료)
```

LangGraph 조건부 라우팅: 품질 게이트 통과 페이지는 Stage 6으로 직행하고,
실패 페이지만 Stage 5(폴백)를 거친 뒤 합류합니다.

---

## IN/OUT 인터페이스

### `OCRv1Pipeline.ingest()`

```python
async def ingest(
    self,
    pdf_bytes: bytes,         # 원본 PDF 이진 데이터
    filename: str,            # 원본 파일명 (컬렉션명 자동 생성에 사용)
    collection_name: str = "" # Qdrant 컬렉션명 (빈 값이면 파일명 기반 자동 생성)
) -> dict:                    # OCRPipelineState 와 동일한 구조의 딕셔너리
```

반환 딕셔너리 주요 키:

| 키 | 타입 | 설명 |
|---|---|---|
| `pipeline_status` | `str` | `"done"` \| `"error"` |
| `total_pages` | `int` | PDF 전체 페이지 수 |
| `chunks` | `list[ChunkRecord]` | 생성된 청크 목록 |
| `embedded_count` | `int` | 실제 임베딩·저장된 청크 수 |
| `collection_name` | `str` | 저장된 Qdrant 컬렉션명 |
| `quality_scores` | `list[QualityScore]` | 페이지별 품질 점수 |
| `timings` | `dict[str, float]` | Stage별 소요 시간(초) |
| `error_message` | `str \| None` | 오류 발생 시 메시지 |

### `OCRv1Pipeline.search()`

```python
async def search(
    self,
    query: str,              # 검색 쿼리 문자열
    collection_name: str,    # 검색 대상 Qdrant 컬렉션명
    top_k: int = 5           # 반환할 최상위 결과 수 (1~50)
) -> list[dict]:             # SearchHit 딕셔너리 목록
```

반환 딕셔너리 항목 키:

| 키 | 타입 | 설명 |
|---|---|---|
| `chunk_id` | `str` | 청크 고유 식별자 |
| `text` | `str` | 청크 본문 텍스트 |
| `score` | `float` | 리랭킹 후 관련도 점수 |
| `section_title` | `str` | 청크가 속한 섹션 제목 |
| `page_nums` | `list[int]` | 원본 페이지 번호 목록 |

---

## API 엔드포인트

| 메서드 | 경로 | 설명 |
|---|---|---|
| `POST` | `/api/ocr/v1/ingest` | PDF 인제스트 (multipart/form-data) |
| `POST` | `/api/ocr/v1/search` | RAG 하이브리드 검색 (JSON) |
| `GET` | `/health` | 헬스체크 |
| `GET` | `/` | 테스트 HTML 페이지로 리다이렉트 |
| `GET` | `/static/ocr_v1.html` | 한국어 테스트 페이지 |

---

## 환경변수

| 변수명 | 기본값 | 설명 |
|---|---|---|
| `OCR_V1_PORT` | `8005` | FastAPI 서버 바인딩 포트 |
| `OCR_V1_PRIMARY_ENGINE` | `marker` | 기본 OCR 엔진 |
| `OCR_V1_FALLBACK_ENGINE` | `mineru` | 품질 실패 시 폴백 엔진 |
| `OCR_V1_MARKER_TIMEOUT_SEC` | `300` | Marker 엔진 호출 타임아웃(초) |
| `OCR_V1_MARKER_BATCH_MULTIPLIER` | `2` | Marker 배치 크기 배율 |
| `OCR_V1_MARKER_USE_LLM_MODEL` | `""` | LLM 교정 모델명 (비면 비활성) |
| `OCR_V1_QUALITY_PASS_THRESHOLD` | `0.7` | 품질 통과 최소 점수 |
| `OCR_V1_CHAR_CORRUPTION_MAX` | `0.05` | 최대 허용 문자 오염률 |
| `OCR_V1_TABLE_INTEGRITY_MIN` | `0.8` | 표 무결성 최소 점수 |
| `OCR_V1_FORMULA_PRESERVATION_MIN` | `0.9` | 수식 보존 최소 점수 |
| `OCR_V1_READING_ORDER_MIN` | `0.85` | 읽기 순서 최소 점수 |
| `OCR_V1_CHUNK_MIN_TOKENS` | `600` | 섹션 청크 최소 토큰 수 |
| `OCR_V1_CHUNK_MAX_TOKENS` | `1200` | 섹션 청크 최대 토큰 수 |
| `OCR_V1_EMBEDDING_MODEL` | `BAAI/bge-m3` | Dense+Sparse 임베딩 모델 |
| `OCR_V1_EMBEDDING_BATCH_SIZE` | `32` | 임베딩 배치 크기 |
| `OCR_V1_QDRANT_URL` | `http://localhost:6333` | Qdrant 서버 URL |
| `OCR_V1_QDRANT_COLLECTION` | `ocr_v1_chunks` | 기본 Qdrant 컬렉션명 |
| `OCR_V1_RERANKER_MODEL` | `BAAI/bge-reranker-v2-m3` | 크로스인코더 리랭킹 모델 |
| `OCR_V1_RERANK_TOP_K` | `10` | 리랭킹 전 초기 검색 결과 수 |
| `OCR_V1_MAX_QUALITY_RETRIES` | `1` | 폴백 최대 재시도 횟수 |

---

## 의존성

```
marker-pdf          # Marker OCR 엔진 (born-digital 최적화)
magic-pdf           # MinerU OCR 엔진 (scanned 폴백)
FlagEmbedding       # BGE-M3 Dense+Sparse 임베딩
qdrant-client       # Qdrant 벡터 저장소 클라이언트
tiktoken            # cl100k_base 토크나이저 (청킹용)
langgraph           # StateGraph 파이프라인 오케스트레이터
fastapi             # REST API 프레임워크
uvicorn             # ASGI 서버
python-multipart    # multipart/form-data 파일 업로드 지원
```

---

## 사용 예시

### Python 직접 호출

```python
import asyncio
from app.modules.OCR_v1.connector import OCRv1Pipeline

async def main():
    pipeline = OCRv1Pipeline()

    # PDF 인제스트
    with open("document.pdf", "rb") as f:
        pdf_bytes = f.read()

    state = await pipeline.ingest(pdf_bytes, "document.pdf", "my_collection")
    print(f"상태: {state['pipeline_status']}, 청크 수: {len(state['chunks'])}")

    # RAG 검색
    hits = await pipeline.search("검색 쿼리", "my_collection", top_k=5)
    for hit in hits:
        print(f"[{hit['score']:.4f}] {hit['section_title']}: {hit['text'][:100]}")

asyncio.run(main())
```

### curl 예시

```bash
# PDF 인제스트
curl -X POST http://localhost:8005/api/ocr/v1/ingest \
  -F "file=@document.pdf" \
  -F "collection_name=my_collection"

# RAG 검색
curl -X POST http://localhost:8005/api/ocr/v1/search \
  -H "Content-Type: application/json" \
  -d '{"query": "검색 쿼리", "collection_name": "my_collection", "top_k": 5}'

# 헬스체크
curl http://localhost:8005/health
```

### 서버 실행 (샌드박스)

```bash
# uv venv 환경에서 실행
uv venv
uv pip install -r requirements.txt
uv run uvicorn OCR_v1.app.main:app --port 8005
```

---

## 폴백·오류 정책

| 상황 | 처리 방식 |
|---|---|
| 품질 게이트 실패 | MinerU 엔진으로 폴백 재추출 (최대 `OCR_V1_MAX_QUALITY_RETRIES` 회) |
| 폴백 후에도 품질 미달 | best-effort 진행 — 낮은 점수 그대로 청킹·저장 (데이터 손실 방지) |
| 파이프라인 전체 예외 | `pipeline_status="error"`, `error_message` 에 원인 기록, HTTP 200 반환 |
| PDF 형식 오류 | HTTP 400 + 상세 메시지 반환 |

---

## backend-fastapi 이식 방법

1. `OCR_v1/` 폴더 전체를 `backend-fastapi/app/modules/OCR_v1/` 로 복사합니다.
2. `.env` 에 위 환경변수 목록을 추가합니다.
3. `backend-fastapi/app/modules/OCR_v1/app/routers/__init__.py` 의 라우터를
   `backend-fastapi/app/main.py` 의 `include_router` 에 등록합니다.
4. `OCR_v1/connector.py` 의 `OCRv1Pipeline` 을 각 에이전트 또는 서비스 레이어에서 import합니다.
5. Qdrant 서버 URL(`OCR_V1_QDRANT_URL`)이 프로덕션 환경에 맞게 설정됐는지 확인합니다.

> 주의: 이식 후 모든 상대 import(`from ...connector import ...`) 경로가 새 패키지 루트 기준으로
> 올바른지 검토하세요.
