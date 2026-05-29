/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.model;

import java.math.BigDecimal;
import java.util.List;

public record ExamAttemptSnapshot(
    String attemptId,
    String examId,
    String answerKeySeal,
    List<ExamQuestion> questions,
    BigDecimal passPercentage) {}
