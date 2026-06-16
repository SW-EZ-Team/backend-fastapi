#!/usr/bin/env bash
# API 컨테이너 기동 시 ChapterStudio qwen27b Modal 앱 자동 배포 보장
# celery worker/beat 또는 Modal 토큰 미설정 시 ensure-deploy는 스킵한다.

# ensure-deploy 실패가 컨테이너 기동을 막지 않도록 set -e는 사용하지 않는다.

_should_run_modal_ensure_deploy() {
  # api 컨테이너(uvicorn)에서만 실행
  if [[ "${1:-}" != "uvicorn" ]]; then
    return 1
  fi

  # MODAL_ENSURE_DEPLOY: 미설정=활성, 0/false=비활성
  local toggle
  toggle="$(printf '%s' "${MODAL_ENSURE_DEPLOY:-}" | tr '[:upper:]' '[:lower:]')"
  case "${toggle}" in
    0 | false) return 1 ;;
  esac

  # Modal 인증 토큰이 둘 다 있어야 deploy 가능
  if [[ -z "${MODAL_TOKEN_ID:-}" || -z "${MODAL_TOKEN_SECRET:-}" ]]; then
    return 1
  fi

  return 0
}

_run_modal_ensure_deploy() {
  local app_path="${MODAL_DEPLOY_APP_PATH:-app/modules/ChapterStudio_V1/deploy/modal_app.py}"
  local timeout_sec="${MODAL_DEPLOY_TIMEOUT:-180}"

  if command -v timeout >/dev/null 2>&1; then
    if timeout "${timeout_sec}" modal deploy "${app_path}"; then
      echo "[modal-ensure-deploy] 성공: ${app_path}"
    else
      echo "[modal-ensure-deploy] 실패(타임아웃 또는 오류): ${app_path} — 서비스는 폴백 모델로 계속 기동합니다."
    fi
  else
    if modal deploy "${app_path}"; then
      echo "[modal-ensure-deploy] 성공: ${app_path}"
    else
      echo "[modal-ensure-deploy] 실패: ${app_path} — 서비스는 폴백 모델로 계속 기동합니다."
    fi
  fi
}

if _should_run_modal_ensure_deploy "${1:-}"; then
  _run_modal_ensure_deploy || true
fi

exec "$@"