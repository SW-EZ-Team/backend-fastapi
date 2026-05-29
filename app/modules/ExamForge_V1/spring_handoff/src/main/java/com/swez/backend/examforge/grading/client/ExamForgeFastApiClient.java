/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.client;

import com.swez.backend.examforge.grading.exception.ExamForgeGradingErrorCode;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.GradingMode;
import com.swez.backend.examforge.grading.model.QuestionGrade;
import com.swez.backend.examforge.grading.model.RubricCriterion;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import com.swez.backend.examforge.grading.port.ExamForgeRubricGradingPort;
import com.swez.backend.global.exception.CustomException;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.Locale;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.boot.autoconfigure.condition.ConditionalOnBean;
import org.springframework.http.HttpStatusCode;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;

@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnBean(name = "examForgeRestClient")
public class ExamForgeFastApiClient implements ExamForgeRubricGradingPort {

  private final RestClient examForgeRestClient;

  @Override
  public List<QuestionGrade> gradeRubricQuestions(
      ExamAttemptSnapshot snapshot, List<SubmittedAnswer> rubricAnswers) {
    log.info(
        "[ExamForgeFastApiClient] gradeRubricQuestions() - START | attemptId: {}, count: {}",
        snapshot.attemptId(),
        rubricAnswers.size());

    if (rubricAnswers.isEmpty()) {
      return List.of();
    }

    List<ExamQuestion> rubricQuestions =
        snapshot.questions().stream()
            .filter(question -> containsAnswer(rubricAnswers, question.questionId()))
            .toList();

    try {
      FastApiGradeSubmissionResponse response =
          examForgeRestClient
              .post()
              .uri("/api/exam-forge/grade-submission")
              .body(FastApiGradeSubmissionRequest.from(snapshot, rubricQuestions, rubricAnswers))
              .retrieve()
              .onStatus(HttpStatusCode::isError, (request, rawResponse) -> {
                String body = new String(rawResponse.getBody().readAllBytes(), StandardCharsets.UTF_8);
                log.warn(
                    "[ExamForgeFastApiClient] gradeRubricQuestions() - FastAPI error | status: {}, body: {}",
                    rawResponse.getStatusCode(),
                    body);
                throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
              })
              .body(FastApiGradeSubmissionResponse.class);

      if (response == null || response.results() == null) {
        throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
      }
      List<QuestionGrade> result = response.results().stream().map(this::toGrade).toList();
      log.info(
          "[ExamForgeFastApiClient] gradeRubricQuestions() - END | attemptId: {}, count: {}",
          snapshot.attemptId(),
          result.size());
      return result;
    } catch (CustomException e) {
      throw e;
    } catch (RestClientException e) {
      log.warn("[ExamForgeFastApiClient] gradeRubricQuestions() - ERROR | attemptId: {}", snapshot.attemptId(), e);
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    } catch (RuntimeException e) {
      log.warn(
          "[ExamForgeFastApiClient] gradeRubricQuestions() - invalid FastAPI response | attemptId: {}",
          snapshot.attemptId(),
          e);
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
  }

  private boolean containsAnswer(List<SubmittedAnswer> answers, String questionId) {
    return answers.stream().anyMatch(answer -> questionId.equals(answer.questionId()));
  }

  private QuestionGrade toGrade(FastApiQuestionGradeResponse response) {
    if (response == null
        || response.questionId() == null
        || response.templateId() == null
        || response.score() == null
        || response.maxScore() == null
        || response.gradingMode() == null
        || response.feedback() == null
        || response.rubricBreakdown() == null) {
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
    return new QuestionGrade(
        response.questionId(),
        response.templateId(),
        response.score(),
        response.maxScore(),
        response.correct(),
        parseGradingMode(response.gradingMode()),
        response.feedback(),
        response.rubricBreakdown().stream()
            .map(item -> new RubricCriterion(item.criterion(), item.score(), item.maxScore(), item.reason()))
            .toList(),
        response.confidence(),
        response.needsManualReview());
  }

  private GradingMode parseGradingMode(String value) {
    try {
      return GradingMode.valueOf(value.toUpperCase(Locale.ROOT));
    } catch (IllegalArgumentException e) {
      throw new CustomException(ExamForgeGradingErrorCode.FASTAPI_GRADING_FAILED);
    }
  }
}
