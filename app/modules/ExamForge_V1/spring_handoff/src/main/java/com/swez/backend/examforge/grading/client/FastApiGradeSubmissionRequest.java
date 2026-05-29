/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.client;

import com.fasterxml.jackson.annotation.JsonProperty;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import java.math.BigDecimal;
import java.util.List;

public record FastApiGradeSubmissionRequest(
    @JsonProperty("attempt_id") String attemptId,
    @JsonProperty("exam_id") String examId,
    @JsonProperty("answer_key_seal") String answerKeySeal,
    List<ExamQuestion> questions,
    @JsonProperty("submitted_answers") List<SubmittedAnswer> submittedAnswers,
    @JsonProperty("pass_percentage") BigDecimal passPercentage) {

  public static FastApiGradeSubmissionRequest from(
      ExamAttemptSnapshot snapshot, List<ExamQuestion> questions, List<SubmittedAnswer> answers) {
    return new FastApiGradeSubmissionRequest(
        snapshot.attemptId(),
        snapshot.examId(),
        snapshot.answerKeySeal(),
        questions,
        answers,
        snapshot.passPercentage());
  }
}
