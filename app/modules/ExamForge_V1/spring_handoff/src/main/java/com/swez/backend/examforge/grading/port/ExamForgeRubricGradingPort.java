/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.port;

import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.QuestionGrade;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import java.util.List;

public interface ExamForgeRubricGradingPort {

  List<QuestionGrade> gradeRubricQuestions(
      ExamAttemptSnapshot snapshot, List<SubmittedAnswer> rubricAnswers);
}
