/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.dto.response;

import com.swez.backend.examforge.grading.model.GradingStatus;
import io.swagger.v3.oas.annotations.media.Schema;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import lombok.Builder;

@Builder
@Schema(description = "시험 제출 채점 공개 응답 DTO")
public record ExamSubmissionGradeResponse(
    @Schema(description = "응시 시도 ID", example = "attempt_20260526_0001")
        String attemptId,
    @Schema(description = "시험 ID", example = "exam_abc123")
        String examId,
    @Schema(description = "총 취득점", example = "78.5")
        BigDecimal totalScore,
    @Schema(description = "총 만점", example = "100.0")
        BigDecimal maxScore,
    @Schema(description = "백분율 점수", example = "78.5")
        BigDecimal percentage,
    @Schema(description = "합격 여부", example = "true")
        boolean passed,
    @Schema(description = "전체 채점 상태", example = "GRADED")
        GradingStatus gradingStatus,
    @Schema(description = "채점 완료 시각")
        OffsetDateTime gradedAt,
    @Schema(description = "문항별 채점 결과")
        List<QuestionGradeResponse> results) {}
