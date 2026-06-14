# ObjectStorage_V1

S3 API 호환 객체 저장소에 대용량 파일을 업로드하는 라이브러리형 모듈임. 로컬 테스트는 MinIO를 사용하고, 운영은 같은 코드에서 AWS S3 엔드포인트로 전환함.

## IN/OUT

| 구분 | 내용 |
|---|---|
| 입력 | `data: bytes`, `key: str`, `content_type: str` |
| 출력 | 브라우저가 바로 GET 할 수 있는 공개 URL 문자열 |
| 공개 API | `from app.modules.ObjectStorage_V1 import put_object, s3_enabled, to_internal_url` |

```python
url = await put_object(
    data=audio_bytes,
    key="tts/1710000000000_0_gemini-tts_abcd1234.wav",
    content_type="audio/wav",
)
```

## 환경변수

| 키 | 기본값 | 설명 |
|---|---|---|
| `S3_ENABLED` | `false` | `true`일 때만 S3 업로드를 사용함 |
| `S3_ENDPOINT_URL` | 빈 값 | 로컬 MinIO는 `http://minio:9000`, AWS는 빈 값 |
| `S3_REGION` | `us-east-1` | S3 리전 |
| `S3_BUCKET` | `sw-ez-media` | 업로드 버킷 |
| `S3_ACCESS_KEY` | 빈 값 | MinIO 또는 명시 자격증명 |
| `S3_SECRET_KEY` | 빈 값 | MinIO 또는 명시 자격증명 |
| `S3_PUBLIC_URL_BASE` | 빈 값 | 브라우저 공개 접근 기준 URL |

로컬 compose 기본값은 `S3_ENDPOINT_URL=http://minio:9000`, `S3_PUBLIC_URL_BASE=http://localhost:9000/sw-ez-media`임. 컨테이너 내부 업로드는 `minio` 서비스명을 쓰고, 브라우저 응답 URL은 `localhost`를 써야 하기 때문임.

`to_internal_url(url)`은 그 반대 방향임 — DB 등에 저장된 브라우저용 공개 URL(`S3_PUBLIC_URL_BASE` 시작)을 컨테이너 내부에서 다운로드 가능한 endpoint URL로 되돌림. 공개 베이스로 시작하지 않거나 설정이 비어 있으면 원본을 그대로 반환함 (AWS 운영 환경 no-op). TTS 보이스클론의 참조음성 다운로드 경로가 사용함.

## 폴백 정책

이 모듈은 `S3_ENABLED=false`이면 업로드하지 않고 명확한 설정 예외를 발생시킴. 음성 파이프라인은 이 값을 먼저 확인해 기존 로컬 `media/tts/` 저장으로 폴백함.

`S3_ENABLED=true`에서 업로드가 실패하면 로컬 저장으로 조용히 넘어가지 않음. 사용자가 S3 저장을 명시한 상태이므로 컨테이너 로컬 파일 소실을 숨기지 않기 위해 실패를 예외로 노출함.
