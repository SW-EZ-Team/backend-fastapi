/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.client;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;
import java.util.List;

public record FastApiQuestionGradeResponse(
    @JsonProperty("question_id") String questionId,
    @JsonProperty("template_id") String templateId,
    BigDecimal score,
    @JsonProperty("max_score") BigDecimal maxScore,
    @JsonProperty("is_correct") boolean correct,
    @JsonProperty("grading_mode") String gradingMode,
    String feedback,
    @JsonProperty("rubric_breakdown") List<FastApiRubricCriterionResponse> rubricBreakdown,
    double confidence,
    @JsonProperty("needs_manual_review") boolean needsManualReview) {}
