/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.mapper;

import com.swez.backend.examforge.grading.dto.request.SubmittedAnswerRequest;
import com.swez.backend.examforge.grading.dto.response.ExamSubmissionGradeResponse;
import com.swez.backend.examforge.grading.dto.response.QuestionGradeResponse;
import com.swez.backend.examforge.grading.dto.response.RubricCriterionResponse;
import com.swez.backend.examforge.grading.model.ExamGradeResult;
import com.swez.backend.examforge.grading.model.QuestionGrade;
import com.swez.backend.examforge.grading.model.RubricCriterion;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import org.springframework.stereotype.Component;

@Component
public class ExamGradingMapper {

  public SubmittedAnswer toDomain(SubmittedAnswerRequest request) {
    return new SubmittedAnswer(request.questionId(), request.answer());
  }

  public ExamSubmissionGradeResponse toResponse(ExamGradeResult result) {
    return ExamSubmissionGradeResponse.builder()
        .attemptId(result.attemptId())
        .examId(result.examId())
        .totalScore(result.totalScore())
        .maxScore(result.maxScore())
        .percentage(result.percentage())
        .passed(result.passed())
        .gradingStatus(result.gradingStatus())
        .gradedAt(result.gradedAt())
        .results(result.results().stream().map(this::toResponse).toList())
        .build();
  }

  private QuestionGradeResponse toResponse(QuestionGrade grade) {
    return QuestionGradeResponse.builder()
        .questionId(grade.questionId())
        .templateId(grade.templateId())
        .score(grade.score())
        .maxScore(grade.maxScore())
        .correct(grade.correct())
        .gradingMode(grade.gradingMode())
        .feedback(grade.feedback())
        .rubricBreakdown(grade.rubricBreakdown().stream().map(this::toResponse).toList())
        .confidence(grade.confidence())
        .needsManualReview(grade.needsManualReview())
        .build();
  }

  private RubricCriterionResponse toResponse(RubricCriterion criterion) {
    return RubricCriterionResponse.builder()
        .criterion(criterion.criterion())
        .score(criterion.score())
        .maxScore(criterion.maxScore())
        .reason(criterion.reason())
        .build();
  }
}
