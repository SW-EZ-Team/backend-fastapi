/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.service;

import com.swez.backend.examforge.grading.dto.request.ExamSubmissionGradeRequest;
import com.swez.backend.examforge.grading.dto.request.SubmittedAnswerRequest;
import com.swez.backend.examforge.grading.dto.response.ExamSubmissionGradeResponse;
import com.swez.backend.examforge.grading.exception.ExamForgeGradingErrorCode;
import com.swez.backend.examforge.grading.mapper.ExamGradingMapper;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamGradeResult;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.GradingStatus;
import com.swez.backend.examforge.grading.model.QuestionGrade;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import com.swez.backend.examforge.grading.port.ExamAttemptRepositoryPort;
import com.swez.backend.examforge.grading.port.ExamForgeRubricGradingPort;
import com.swez.backend.examforge.grading.support.QuestionTemplatePolicy;
import com.swez.backend.global.exception.CustomException;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.stereotype.Service;

@Slf4j
@Service
@RequiredArgsConstructor
@ConditionalOnBean({ExamAttemptRepositoryPort.class, ExamForgeRubricGradingPort.class})
public class ExamSubmissionGradingService {

  private final ExamAttemptRepositoryPort attemptRepository;
  private final ExamForgeRubricGradingPort rubricGradingPort;
  private final DeterministicQuestionScorer deterministicScorer;
  private final ExamGradingMapper mapper;
  private final GradingLeakGuard leakGuard;
  private final QuestionTemplatePolicy templatePolicy = new QuestionTemplatePolicy();

  public ExamSubmissionGradeResponse gradeSubmission(ExamSubmissionGradeRequest request) {
    ExamAttemptSnapshot snapshot =
        attemptRepository
            .findGradingSnapshot(request.attemptId())
            .orElseThrow(() -> new CustomException(ExamForgeGradingErrorCode.ATTEMPT_NOT_FOUND));
    List<SubmittedAnswer> submittedAnswers =
        safeSubmittedAnswers(request).stream().map(this::toDomainAnswer).toList();

    ExamGradeResult result = gradeSnapshot(snapshot, submittedAnswers);
    ExamSubmissionGradeResponse response = mapper.toResponse(result);
    leakGuard.assertPublicResponseSafe(response, snapshot);
    attemptRepository.saveGradingResult(result);
    return response;
  }

  public ExamGradeResult gradeSnapshot(
      ExamAttemptSnapshot snapshot, List<SubmittedAnswer> submittedAnswers) {
    validateSnapshot(snapshot);
    Map<String, ExamQuestion> questionsById = questionMap(snapshot.questions());
    Map<String, SubmittedAnswer> answersByQuestionId = submittedAnswerMap(questionsById, submittedAnswers);
    Map<String, QuestionGrade> deterministicGrades = new HashMap<>();
    List<SubmittedAnswer> rubricAnswers = new ArrayList<>();

    for (ExamQuestion question : snapshot.questions()) {
      SubmittedAnswer submittedAnswer = answersByQuestionId.get(question.questionId());
      if (submittedAnswer == null) {
        deterministicGrades.put(question.questionId(), deterministicScorer.unanswered(question));
        continue;
      }
      if (templatePolicy.isRubric(question.templateId())) {
        QuestionGrade exactGrade = deterministicScorer.scoreExact(question, submittedAnswer.answer());
        if (exactGrade.correct()) {
          deterministicGrades.put(question.questionId(), exactGrade);
        } else {
          rubricAnswers.add(submittedAnswer);
        }
        continue;
      }
      deterministicGrades.put(
          question.questionId(), deterministicScorer.score(question, submittedAnswer.answer()));
    }

    Map<String, QuestionGrade> rubricGrades = gradeRubricQuestions(snapshot, rubricAnswers, questionsById);
    List<QuestionGrade> orderedGrades = new ArrayList<>();
    for (ExamQuestion question : snapshot.questions()) {
      QuestionGrade deterministicGrade = deterministicGrades.get(question.questionId());
      orderedGrades.add(
          deterministicGrade != null ? deterministicGrade : rubricGrades.get(question.questionId()));
    }

    ExamGradeResult result = aggregate(snapshot, orderedGrades);
    log.info(
        "[ExamSubmissionGradingService] graded attempt | attemptId: {}, questions: {}, status: {}",
        snapshot.attemptId(),
        orderedGrades.size(),
        result.gradingStatus());
    return result;
  }

  private void validateSnapshot(ExamAttemptSnapshot snapshot) {
    if (snapshot == null
        || isBlank(snapshot.attemptId())
        || isBlank(snapshot.examId())
        || isBlank(snapshot.answerKeySeal())
        || snapshot.questions() == null
        || snapshot.questions().isEmpty()) {
      throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
    }
  }

  private Map<String, ExamQuestion> questionMap(List<ExamQuestion> questions) {
    Map<String, ExamQuestion> result = new LinkedHashMap<>();
    for (ExamQuestion question : questions) {
      if (question == null || isBlank(question.questionId())) {
        throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
      }
      if (result.put(question.questionId(), question) != null) {
        throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
      }
    }
    return result;
  }

  private Map<String, SubmittedAnswer> submittedAnswerMap(
      Map<String, ExamQuestion> questionsById, List<SubmittedAnswer> submittedAnswers) {
    if (submittedAnswers == null || submittedAnswers.isEmpty()) {
      return Map.of();
    }
    Map<String, SubmittedAnswer> result = new LinkedHashMap<>();
    for (SubmittedAnswer answer : submittedAnswers) {
      if (answer == null || isBlank(answer.questionId()) || answer.answer() == null) {
        throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
      }
      if (!questionsById.containsKey(answer.questionId())) {
        throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
      }
      if (result.put(answer.questionId(), answer) != null) {
        throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
      }
    }
    return result;
  }

  private Map<String, QuestionGrade> gradeRubricQuestions(
      ExamAttemptSnapshot snapshot,
      List<SubmittedAnswer> rubricAnswers,
      Map<String, ExamQuestion> questionsById) {
    if (rubricAnswers.isEmpty()) {
      return Map.of();
    }
    List<QuestionGrade> grades = rubricGradingPort.gradeRubricQuestions(snapshot, rubricAnswers);
    Set<String> requestedIds = new HashSet<>();
    rubricAnswers.forEach(answer -> requestedIds.add(answer.questionId()));
    Map<String, QuestionGrade> result = new LinkedHashMap<>();
    for (QuestionGrade grade : grades) {
      validateRubricGrade(grade, requestedIds, questionsById);
      if (result.put(grade.questionId(), grade) != null) {
        throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
      }
    }
    if (!result.keySet().equals(requestedIds)) {
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
    return result;
  }

  private void validateRubricGrade(
      QuestionGrade grade, Set<String> requestedIds, Map<String, ExamQuestion> questionsById) {
    if (grade == null
        || isBlank(grade.questionId())
        || !requestedIds.contains(grade.questionId())
        || grade.score() == null
        || grade.maxScore() == null
        || grade.gradingMode() == null
        || grade.feedback() == null
        || grade.rubricBreakdown() == null) {
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
    BigDecimal expectedMax = questionsById.get(grade.questionId()).pointValue();
    if (grade.score().compareTo(BigDecimal.ZERO) < 0
        || grade.score().compareTo(expectedMax) > 0
        || grade.maxScore().compareTo(expectedMax) != 0) {
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
  }

  private ExamGradeResult aggregate(ExamAttemptSnapshot snapshot, List<QuestionGrade> grades) {
    if (grades.stream().anyMatch(grade -> grade == null || grade.score() == null || grade.maxScore() == null)) {
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
    BigDecimal totalScore = grades.stream().map(QuestionGrade::score).reduce(BigDecimal.ZERO, BigDecimal::add);
    BigDecimal maxScore = grades.stream().map(QuestionGrade::maxScore).reduce(BigDecimal.ZERO, BigDecimal::add);
    BigDecimal percentage =
        maxScore.compareTo(BigDecimal.ZERO) == 0
            ? BigDecimal.ZERO
            : totalScore.multiply(BigDecimal.valueOf(100)).divide(maxScore, 2, RoundingMode.HALF_UP);
    boolean needsManualReview = grades.stream().anyMatch(QuestionGrade::needsManualReview);
    boolean passed = !needsManualReview && percentage.compareTo(passPercentage(snapshot)) >= 0;
    GradingStatus status = needsManualReview ? GradingStatus.MANUAL_REVIEW_REQUIRED : GradingStatus.GRADED;
    return new ExamGradeResult(
        snapshot.attemptId(),
        snapshot.examId(),
        totalScore.setScale(4, RoundingMode.HALF_UP),
        maxScore.setScale(4, RoundingMode.HALF_UP),
        percentage,
        passed,
        status,
        OffsetDateTime.now(),
        grades);
  }

  private BigDecimal passPercentage(ExamAttemptSnapshot snapshot) {
    return snapshot.passPercentage() == null ? BigDecimal.valueOf(60) : snapshot.passPercentage();
  }

  private List<SubmittedAnswerRequest> safeSubmittedAnswers(ExamSubmissionGradeRequest request) {
    if (request.submittedAnswers() == null) {
      return List.of();
    }
    return request.submittedAnswers();
  }

  private SubmittedAnswer toDomainAnswer(SubmittedAnswerRequest request) {
    if (request == null) {
      throw new CustomException(ExamForgeGradingErrorCode.INVALID_SUBMISSION);
    }
    return mapper.toDomain(request);
  }

  private boolean isBlank(String value) {
    return value == null || value.isBlank();
  }
}
