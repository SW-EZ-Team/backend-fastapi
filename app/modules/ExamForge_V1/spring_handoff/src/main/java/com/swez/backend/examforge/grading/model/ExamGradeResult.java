/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.model;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

public record ExamGradeResult(
    String attemptId,
    String examId,
    BigDecimal totalScore,
    BigDecimal maxScore,
    BigDecimal percentage,
    boolean passed,
    GradingStatus gradingStatus,
    OffsetDateTime gradedAt,
    List<QuestionGrade> results) {}
