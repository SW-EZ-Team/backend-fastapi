/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.client;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

public record FastApiGradeSubmissionResponse(
    @JsonProperty("attempt_id") String attemptId,
    @JsonProperty("exam_id") String examId,
    @JsonProperty("total_score") BigDecimal totalScore,
    @JsonProperty("max_score") BigDecimal maxScore,
    BigDecimal percentage,
    boolean passed,
    @JsonProperty("grading_status") String gradingStatus,
    @JsonProperty("graded_at") OffsetDateTime gradedAt,
    List<FastApiQuestionGradeResponse> results) {}
