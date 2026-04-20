# Telegram_control_module

`Telegram_control_module`은 루트의 `Teletest/`에서 검증한 Telegram Bot API 연결 흐름을 `backend-fastapi` 안으로 옮긴 라이브러리형 FastAPI 모듈이다. `Teletest`는 Bot Token, `telegram_chat_id`, 메시지를 입력해 Telegram `sendMessage` 호출이 정상 동작하는지 확인한 테스트 폴더였고, 이 모듈은 그 검증 흐름을 FastAPI가 직접 소유하는 구조로 정리한 것이다.

이 프로젝트에서 실제 Telegram API 호출과 웹훅 수신은 FastAPI가 담당한다. 문서 네이밍은 `Docs/API명세서/API_명세서.md`와 `Docs/ERD/일과_ERD.md`를 기준으로 맞춘다. 공개 웹훅 경로는 `POST /telegram/webhook`이고, 계정 연동 정본 필드는 `telegram_account.telegram_chat_id`이며, 송수신 로그 테이블은 `telegram_message`다.

---

## 이식 기준

| 원본 `Teletest` | 이식 후 위치 | 설명 |
|---|---|---|
| `server.js` | `api/router.py`, `services/telegram_client.py` | Express `/api/send` 흐름을 FastAPI `/telegram/sendMessage` 라우터와 Telegram API 클라이언트로 분리함 |
| `public/index.html` | `web_console/index.html` | 브라우저에서 메시지 전송을 확인하는 테스트 콘솔로 유지함 |
| `package.json`, `package-lock.json` | 이식 제외 | Node 실행 환경용 의존성 파일이므로 FastAPI 모듈에는 포함하지 않음 |
| `node_modules/` | 이식 제외 | 설치 산출물이므로 백엔드 소스 모듈에 포함하지 않음 |

원본의 핵심 검증 포인트는 유지한다. Bot Token, `telegram_chat_id`, 메시지를 받아 Telegram Bot API `sendMessage`로 전송하고, 실패 시 Telegram `description`을 사용자에게 돌려주는 흐름이다. 다만 런타임은 Express가 아니라 FastAPI로 바꾸었고, 토큰은 환경변수 `TELEGRAM_BOT_TOKEN`을 우선 사용할 수 있게 했다.

---

## 폴더 구조

```text
Telegram_control_module/
├── __init__.py
├── config.py
├── schemas.py
├── Telegram_control_module.md
├── api/
│   ├── __init__.py
│   └── router.py
├── parsers/
│   ├── __init__.py
│   └── update_parser.py
├── services/
│   ├── __init__.py
│   └── telegram_client.py
├── tests/
│   ├── test_schemas.py
│   └── test_update_parser.py
└── web_console/
    └── index.html
```

### `api/`

FastAPI 라우터가 들어간다. 현재 공개 경로는 다음과 같다.

| Method | Path | 역할 |
|---|---|---|
| `GET` | `/telegram/health` | 모듈 라우터가 연결됐는지 확인함 |
| `GET` | `/telegram/console` | 브라우저 테스트 콘솔 HTML을 반환함 |
| `POST` | `/telegram/sendMessage` | Telegram Bot API `sendMessage`를 호출함 |
| `POST` | `/telegram/webhook` | API 명세서의 Telegram Update 웹훅을 수신함 |

`router.py`는 라우터 생성 함수 `create_router()`를 제공한다. 테스트나 향후 통합 코드에서 `TelegramClient`를 주입할 수 있게 하기 위한 구조다.

### `services/`

Telegram 외부 API 호출을 담당한다. `telegram_client.py`는 표준 라이브러리 `urllib`만 사용한다. 이유는 단순하다. 현재 `backend-fastapi` 의존성에 HTTP 클라이언트 라이브러리를 새로 추가하지 않고, 검증된 송신 흐름을 바로 옮기기 위해서다.

주요 공개 객체는 다음과 같다.

| 객체 | 역할 |
|---|---|
| `TelegramClient` | Telegram Bot API 호출 담당 |
| `TelegramApiError` | Telegram API 실패를 모듈 내부 예외로 정규화 |

`send_message()`는 FastAPI 이벤트 루프를 막지 않도록 내부에서 `asyncio.to_thread()`로 동기 HTTP 호출을 분리한다.

### `parsers/`

Telegram 웹훅 Update 객체에서 ERD 저장 후보 필드를 뽑는 파서가 들어간다. 현재 `message`, `edited_message`, `channel_post`, `edited_channel_post`, `callback_query.message`를 지원한다.

주요 함수는 다음과 같다.

```python
from app.modules.Telegram_control_module import extract_telegram_message_summary
```

이 함수는 `telegram_chat_id`, `telegram_msg_id`, `telegram_username`, `content`, `message_type`을 `TelegramMessageSummary`로 정규화한다. `telegram_chat_id`가 없으면 `None`을 반환한다.

### `web_console/`

기존 `Teletest/public/index.html`의 역할을 이어받은 브라우저 테스트 콘솔이다. FastAPI 실행 후 아래 경로에서 접근한다.

```text
http://localhost:8000/telegram/console
```

콘솔은 `/telegram/sendMessage`를 호출한다. `Bot Token` 입력값을 비워두면 서버의 `TELEGRAM_BOT_TOKEN` 환경변수를 사용한다.

### `tests/`

모듈 단위 회귀 테스트가 들어간다.

| 테스트 파일 | 검증 내용 |
|---|---|
| `test_schemas.py` | ERD 기준 `telegram_chat_id` 입력 필드, 빈 메시지 차단 |
| `test_update_parser.py` | 일반 메시지·콜백 쿼리·chat 미포함 Update 처리 |

---

## 사용 방법

### FastAPI 라우터 연결

`backend-fastapi/main.py`에서 이미 다음 방식으로 연결한다.

```python
from app.modules.Telegram_control_module import router as telegram_control_router

app.include_router(telegram_control_router)
```

### 메시지 전송

```http
POST /telegram/sendMessage
Content-Type: application/json

{
  "token": null,
  "telegram_chat_id": "123456789",
  "message": "테스트 메시지"
}
```

`token`이 `null`이면 서버 환경변수 `TELEGRAM_BOT_TOKEN`을 사용한다. 운영에서는 토큰을 코드, 문서, 로그에 남기지 않는다.

### 웹훅 수신

```http
POST /telegram/webhook
X-Telegram-Bot-Api-Secret-Token: <secret>
Content-Type: application/json

{
  "message": {
    "message_id": 17,
    "chat": {
      "id": 123456789,
      "username": "student_user",
      "first_name": "민준"
    },
    "text": "안녕하세요"
  }
}
```

`TELEGRAM_WEBHOOK_SECRET` 환경변수가 설정돼 있으면 `X-Telegram-Bot-Api-Secret-Token` 헤더와 비교한다. 설정돼 있지 않으면 로컬 테스트 편의를 위해 secret 검증을 건너뛴다. 응답은 API 명세서 그대로 `{"ok": true}` 형태다.

---

## 프로젝트 내 연결 방향

이 모듈은 최종 텔레그램 기능의 연결 출발점이다.

1. 사용자가 봇에 메시지를 보내면 `/telegram/webhook`이 Update를 받는다.
2. `parsers/update_parser.py`가 `telegram_chat_id`를 추출한다.
3. 추출된 `telegram_chat_id`는 향후 `telegram_account.telegram_chat_id` 저장 흐름으로 연결한다.
4. 과제 파일 수신은 같은 웹훅 라우터에서 파일 타입 분기와 Celery 큐 등록으로 확장한다.
5. 채점 완료 후 `services/telegram_client.py`의 송신 기능을 사용해 학생에게 DM을 보낸다.
6. 운영자용 토큰 검증, 관리자 알림, 메시지 내역 조회는 FastAPI 내부 서비스와 관리자 API 연결로 확장한다.

현재 모듈은 DB 쓰기나 Celery 연결을 아직 수행하지 않는다. 이유는 `Teletest`의 검증 범위가 Telegram 연결 자체였기 때문이다. DB 저장, 과제 파일 처리, 채점 큐 연결은 다음 단계에서 이 모듈의 `webhook` 결과를 기반으로 붙이는 것이 맞다.

---

## 환경변수

| 변수 | 설명 |
|---|---|
| `TELEGRAM_BOT_TOKEN` | 기본 봇 토큰. `/telegram/sendMessage` 요청의 `token`이 없을 때 사용함 |
| `TELEGRAM_WEBHOOK_SECRET` | Telegram 웹훅 secret token 검증값 |

토큰은 코드, 문서, 테스트 데이터, 커밋 로그에 저장하지 않는다.

---

## 주의사항

- `node_modules/`는 이식하지 않는다. 설치 산출물을 소스 모듈에 넣지 않기 때문이다.
- 입력 필드는 ERD 정본 컬럼명에 맞춰 `telegram_chat_id`를 사용한다.
- Telegram 외부 API 식별자인 `telegram_chat_id`는 음수 채널 ID까지 고려해 정수로 파싱한다.
- 실제 Telegram API 호출 이름은 문서에 적힌 `sendMessage`, `getMe` 표기를 따른다.
