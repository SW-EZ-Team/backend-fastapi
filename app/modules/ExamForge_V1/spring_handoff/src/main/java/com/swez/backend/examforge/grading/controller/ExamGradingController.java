/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.controller;

import com.swez.backend.examforge.grading.dto.request.ExamSubmissionGradeRequest;
import com.swez.backend.examforge.grading.dto.response.ExamSubmissionGradeResponse;
import com.swez.backend.global.response.ApiResponse;
import io.swagger.v3.oas.annotations.Operation;
import io.swagger.v3.oas.annotations.tags.Tag;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;

@Tag(name = "ExamForge Grading", description = "ExamForge 시험 제출 채점 API")
@RequestMapping("/api/exam-forge/submissions")
public interface ExamGradingController {

  @Operation(
      summary = "시험 제출 채점",
      description = "프론트엔드가 제출한 답안을 서버 저장 스냅샷 기준으로 채점한다. 정답지와 answerKeySeal은 요청/응답에 노출하지 않는다.")
  @PostMapping("/grade")
  ApiResponse<ExamSubmissionGradeResponse> gradeSubmission(
      @Valid @RequestBody ExamSubmissionGradeRequest request);
}
