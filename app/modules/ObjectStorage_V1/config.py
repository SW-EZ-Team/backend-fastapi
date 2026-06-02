"""S3 호환 객체 저장소 환경 설정."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import cache

from dotenv import load_dotenv


class ObjectStorageConfigError(RuntimeError):
    """객체 저장소 설정이 업로드를 수행할 수 없을 때 사용한다."""


@dataclass(frozen=True)
class S3Settings:
    enabled: bool
    endpoint_url: str | None
    region: str
    bucket: str
    access_key: str | None
    secret_key: str | None
    public_url_base: str | None


@cache
def _load_env() -> None:
    """환경 파일은 호출 시점에 한 번만 로드한다."""
    load_dotenv()


def s3_enabled() -> bool:
    """명시적으로 켠 경우에만 S3 업로드를 사용한다."""
    return _bool_value("S3_ENABLED", False)


def load_s3_settings() -> S3Settings:
    """S3 업로드에 필요한 설정을 환경변수에서 읽는다."""
    settings = S3Settings(
        enabled=s3_enabled(),
        endpoint_url=_optional_value("S3_ENDPOINT_URL"),
        region=_optional_value("S3_REGION") or "us-east-1",
        bucket=_optional_value("S3_BUCKET") or "sw-ez-media",
        access_key=_optional_value("S3_ACCESS_KEY"),
        secret_key=_optional_value("S3_SECRET_KEY"),
        public_url_base=_optional_value("S3_PUBLIC_URL_BASE"),
    )
    if settings.enabled and settings.bucket == "":
        raise ObjectStorageConfigError("S3_BUCKET이 비어 있다.")
    return settings


def _optional_value(key: str) -> str | None:
    """빈 문자열은 미설정으로 취급한다."""
    _load_env()
    value = os.environ.get(key)
    if value is None or value == "":
        return None
    return value


def _bool_value(key: str, default: bool) -> bool:
    """운영 환경에서 자주 쓰는 불리언 문자열을 안전하게 해석한다."""
    value = _optional_value(key)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


__all__ = ["ObjectStorageConfigError", "S3Settings", "load_s3_settings", "s3_enabled"]
