# OCR 모델 가중치 파일 목록

이 디렉터리는 PaddleOCR ONNX 가중치 파일을 보관한다.
**가중치 파일은 git 에 커밋하지 않는다** (.gitignore 로 제외).

---

## 현재 적용 중인 파일 구조 (2026-04-17 기준)

> PP-OCRv5 공식 URL 이 현재 접근 불가 상태이므로, `sourcing.md §2 fallback` 승인 경로에 따라
> PP-OCRv4 Korean 가중치를 primary 슬롯에 배치하여 운용 중이다.
> PP-OCRv5 공식 URL 복구 시 primary 슬롯을 v5 로 전환 예정.

```
models/
├── det.onnx               # PP-OCRv4 Chinese Text Detection (opset 11, ~4.5MB)
│                          # 출처: PaddleOCR/ch_PP-OCRv4_det_infer (Apache 2.0)
├── rec.onnx               # PP-OCRv4 Korean Recognition — fp32 full precision (opset 11, ~23MB)
│                          # 출처: HuggingFace cycloneboy/korean_PP-OCRv4_rec_infer (Apache 2.0)
│                          # model.onnx — SHA256: bae0fa6c08d0d86aab39293b31d572749b1e98d2563d6ea532d336c5d07bcf61
├── cls.onnx               # ch_ppocr_mobile_v2.0_cls (opset 11, ~568KB)
│                          # 출처: PaddleOCR/ch_ppocr_mobile_v2.0_cls_infer (Apache 2.0)
├── ppocr_keys_v1.txt      # 인식 문자 사전 (한국어 + 영어 + 중국어)
│                          # 출처: PaddleOCR 공식 리포 (Apache 2.0)
└── fallback/              # 현재 비어 있음 (primary 슬롯에 v4 운용 중)
```

### 백업 파일 (임시 보존)

| 파일 | 설명 |
|---|---|
| `rec_fp16_legacy.onnx` | 교체 전 fp16 rec 모델 (~12MB). 품질 비교 검증 후 삭제 예정 |

---

## 파일별 출처 및 라이선스

| 파일 | 출처 저장소 | 라이선스 | 상업 이용 |
|---|---|---|---|
| `det.onnx` | PaddleOCR `ch_PP-OCRv4_det_infer` | Apache 2.0 | 허용 |
| `rec.onnx` | HuggingFace `cycloneboy/korean_PP-OCRv4_rec_infer` | Apache 2.0 | 허용 |
| `cls.onnx` | PaddleOCR `ch_ppocr_mobile_v2.0_cls_infer` | Apache 2.0 | 허용 |
| `ppocr_keys_v1.txt` | PaddleOCR 공식 리포 | Apache 2.0 | 허용 |

---

## SHA-256 해시 슬롯

수동 검증 시 아래 값과 대조한다.

| 파일 | SHA-256 |
|---|---|
| `rec.onnx` (fp32 23MB) | `bae0fa6c08d0d86aab39293b31d572749b1e98d2563d6ea532d336c5d07bcf61` |
| `det.onnx` | (미기록 — 추후 추가) |
| `cls.onnx` | (미기록 — 추후 추가) |

검증 명령:
```bash
shasum -a 256 ai_connectors/ocr/models/rec.onnx
```

---

## 다운로드 절차

자세한 소싱 경로와 변환 명령은 `Docs/AI플로우/paddleocr_onnx_sourcing.md` 를 참조한다.

### 현재 운용 경로 (PP-OCRv4 Korean, fallback-promoted)

```bash
# rec — HuggingFace 직접 다운로드 (fp32)
curl -L --fail \
  "https://huggingface.co/cycloneboy/korean_PP-OCRv4_rec_infer/resolve/main/model.onnx" \
  -o ai_connectors/ocr/models/rec.onnx
```

### PP-OCRv5 전환 시 (URL 복구 후)

```bash
# rec 모델 (Korean mobile v5)
wget https://paddleocr.bj.bcebos.com/PP-OCRv5/Korean/korean_PP-OCRv5_mobile_rec_infer.tar
tar -xf korean_PP-OCRv5_mobile_rec_infer.tar
paddle2onnx --model_dir korean_PP-OCRv5_mobile_rec_infer \
  --model_filename inference.pdmodel \
  --params_filename inference.pdiparams \
  --save_file models/rec.onnx \
  --opset_version 17
```

---

## 라이선스

| 항목 | 라이선스 | 상업 이용 |
|---|---|---|
| PaddleOCR 코드 | Apache 2.0 | 허용 |
| PP-OCRv4/v5 가중치 | Apache 2.0 | 허용 |
| paddle2onnx | Apache 2.0 | 허용 |
| onnxruntime | MIT | 허용 |

PyMuPDF(AGPL-3.0) 는 의존 경로에 포함하지 않는다.
PDF 래스터화는 lib-rust(pdfium/BSD) 또는 pypdfium2(Apache 2.0/BSD) 로 처리한다.
