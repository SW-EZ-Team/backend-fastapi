/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.exception;

import com.swez.backend.global.exception.model.BaseErrorCode;
import lombok.Getter;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;

@Getter
@RequiredArgsConstructor
public enum ExamForgeGradingErrorCode implements BaseErrorCode {
  ATTEMPT_NOT_FOUND(HttpStatus.NOT_FOUND, "EXAMFORGE_GRADING_001", "시험 응시 정보를 찾을 수 없습니다."),
  INVALID_SUBMISSION(HttpStatus.BAD_REQUEST, "EXAMFORGE_GRADING_002", "제출 답안 형식이 올바르지 않습니다."),
  FASTAPI_GRADING_FAILED(
      HttpStatus.BAD_GATEWAY, "EXAMFORGE_GRADING_003", "AI 루브릭 채점 서버 호출에 실패했습니다."),
  SENSITIVE_RESPONSE_BLOCKED(
      HttpStatus.INTERNAL_SERVER_ERROR, "EXAMFORGE_GRADING_004", "민감한 채점 정보가 응답에 포함되어 차단했습니다.");

  private final HttpStatus httpStatus;
  private final String code;
  private final String message;
}
