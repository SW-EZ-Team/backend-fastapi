/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.port;

import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamGradeResult;
import java.util.Optional;

public interface ExamAttemptRepositoryPort {

  Optional<ExamAttemptSnapshot> findGradingSnapshot(String attemptId);

  void saveGradingResult(ExamGradeResult result);
}
