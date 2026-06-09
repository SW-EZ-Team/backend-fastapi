# FastAPI Dev Deployment Environment Checklist

GitHub Actions의 `ENV_FILE` secret에는 FastAPI EC2에서 생성할 `.env` 내용을 그대로 넣는다.
비밀값은 이 문서에 적지 말고 GitHub Secrets에만 저장한다.

## Required GitHub Secrets

`ENV_FILE` 바깥에 별도 secret으로 관리한다.

```text
DOCKER_USERNAME
DOCKER_PASSWORD
DOCKER_REPO
SSH_HOST
SSH_USERNAME
SSH_PORT
SSH_PRIVATE_KEY
ENV_FILE
```

## Required ENV_FILE Keys

FastAPI 컨테이너 기동과 Spring Redis 공유에 필요한 최소 값이다.

```env
APP_ENV=production
ENVIRONMENT=production
APP_PORT=8000
LOG_LEVEL=info

DATABASE_URL=postgresql://<db_username>:<db_password>@<rds_endpoint>:5432/<db_name>
DATABASE_SCHEMA=chapter_studio

REDIS_URL=redis://:<spring_redis_password>@<spring_private_ip>:6379/4
CELERY_BROKER_URL=redis://:<spring_redis_password>@<spring_private_ip>:6379/1
CELERY_RESULT_BACKEND=redis://:<spring_redis_password>@<spring_private_ip>:6379/2
AGENT_JOB_STORE=redis
AGENT_JOB_REDIS_URL=redis://:<spring_redis_password>@<spring_private_ip>:6379/3
AGENT_JOB_STORE_STRICT=1
AGENT_JOB_EXECUTOR=celery

QDRANT_URL=http://qdrant:6333
OCR_V1_QDRANT_URL=http://qdrant:6333
QDRANT_API_KEY=

FASTAPI_API_KEY=
APP_INTERNAL_TOKEN=
SPRING_BASE_URL=https://<spring_api_domain>/api
EXAMFORGE_ANSWER_KEY_SECRET=

CORS_ORIGINS=https://<frontend_domain>

GEMINI_API_KEY=
GOOGLE_API_KEY=
ANTHROPIC_API_KEY=
CLAUDE_SONNET_API_KEY=

TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=<telegram_bot_username>
```

## Redis Sharing Notes

- FastAPI는 Redis 컨테이너를 만들지 않는다.
- Redis는 Spring EC2의 `ezteam-redis` 컨테이너를 공유한다.
- Spring Redis password는 Spring `ENV_FILE`의 `SPRING_DATA_REDIS_PASSWORD`와 같은 값을 쓴다.
- Redis DB index는 역할별로 나눈다.
  - `4`: FastAPI 공통 Redis URL
  - `1`: Celery broker
  - `2`: Celery result backend
  - `3`: Agent job store
- Spring EC2 보안 그룹은 FastAPI SG에서 오는 `6379/tcp`를 허용해야 한다.
- Spring `docker-compose.dev.yml`의 Redis 서비스는 host port `6379`를 publish해야 한다.

## Port Notes

- FastAPI API는 `8000`으로 통일한다.
- Spring `APP_FASTAPI_BASE_URL`은 `http://<fastapi_private_ip>:8000`이어야 한다.
- Terraform `fastapi_internal_base_url`도 `8000`으로 출력되어야 한다.
