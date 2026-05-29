/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.controller;

import com.swez.backend.examforge.grading.dto.request.ExamSubmissionGradeRequest;
import com.swez.backend.examforge.grading.dto.response.ExamSubmissionGradeResponse;
import com.swez.backend.examforge.grading.service.ExamSubmissionGradingService;
import com.swez.backend.global.response.ApiResponse;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequiredArgsConstructor
@ConditionalOnBean(ExamSubmissionGradingService.class)
public class ExamGradingControllerImpl implements ExamGradingController {

  private final ExamSubmissionGradingService gradingService;

  @Override
  public ApiResponse<ExamSubmissionGradeResponse> gradeSubmission(
      @Valid @RequestBody ExamSubmissionGradeRequest request) {
    return ApiResponse.success(gradingService.gradeSubmission(request), "시험 제출 채점이 완료되었습니다.");
  }
}
