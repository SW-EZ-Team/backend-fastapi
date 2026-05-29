/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.dto.request;

import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;

@Schema(description = "시험 제출 채점 요청 DTO")
public record ExamSubmissionGradeRequest(
    @NotBlank
        @Schema(description = "응시 시도 ID", example = "attempt_20260526_0001")
        String attemptId,
    @Valid
        @NotNull
        @Size(max = 100)
        @Schema(description = "응시자가 제출한 답안 목록")
        List<SubmittedAnswerRequest> submittedAnswers) {}
