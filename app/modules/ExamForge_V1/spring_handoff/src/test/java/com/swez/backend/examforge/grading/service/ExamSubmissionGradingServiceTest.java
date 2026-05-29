/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.service;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import com.swez.backend.examforge.grading.dto.request.ExamSubmissionGradeRequest;
import com.swez.backend.examforge.grading.dto.request.SubmittedAnswerRequest;
import com.swez.backend.examforge.grading.dto.response.ExamSubmissionGradeResponse;
import com.swez.backend.examforge.grading.mapper.ExamGradingMapper;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamGradeResult;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.GradingMode;
import com.swez.backend.examforge.grading.model.GradingStatus;
import com.swez.backend.examforge.grading.model.QuestionGrade;
import com.swez.backend.examforge.grading.model.QuestionOption;
import com.swez.backend.examforge.grading.model.RubricCriterion;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import com.swez.backend.examforge.grading.port.ExamAttemptRepositoryPort;
import com.swez.backend.examforge.grading.port.ExamForgeRubricGradingPort;
import com.swez.backend.global.exception.CustomException;
import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.junit.jupiter.api.Test;

class ExamSubmissionGradingServiceTest {

  private final ObjectMapper objectMapper = JsonMapper.builder().findAndAddModules().build();

  @Test
  void gradeSubmissionScoresObjectiveLocallyAndRoutesRubricToFastApiPort() {
    FakeRepository repository = new FakeRepository(snapshot());
    FakeRubricPort rubricPort =
        new FakeRubricPort(
            List.of(
                new QuestionGrade(
                    "q-essay",
                    "ko_essay",
                    BigDecimal.valueOf(3),
                    BigDecimal.valueOf(5),
                    false,
                    GradingMode.AI_RUBRIC,
                    "주장의 방향은 맞지만 근거가 부족합니다.",
                    List.of(new RubricCriterion("근거", BigDecimal.valueOf(3), BigDecimal.valueOf(5), "부분 충족")),
                    0.91,
                    false)));
    ExamSubmissionGradingService service = service(repository, rubricPort);

    ExamSubmissionGradeResponse response =
        service.gradeSubmission(
            new ExamSubmissionGradeRequest(
                "attempt-1",
                List.of(
                    new SubmittedAnswerRequest("q-choice", objectMapper.valueToTree("B")),
                    new SubmittedAnswerRequest("q-essay", objectMapper.valueToTree("제출 답안")))));

    assertThat(response.totalScore()).isEqualByComparingTo("5.0000");
    assertThat(response.maxScore()).isEqualByComparingTo("7.0000");
    assertThat(response.percentage()).isEqualByComparingTo("71.43");
    assertThat(response.passed()).isTrue();
    assertThat(response.gradingStatus()).isEqualTo(GradingStatus.GRADED);
    assertThat(response.results()).extracting("questionId").containsExactly("q-choice", "q-essay");
    assertThat(rubricPort.lastAnswers).extracting("questionId").containsExactly("q-essay");
    assertThat(repository.savedResult).isNotNull();
  }

  @Test
  void gradeSubmissionRejectsDuplicateSubmittedAnswers() {
    ExamSubmissionGradingService service = service(new FakeRepository(snapshot()), new FakeRubricPort(List.of()));

    ExamSubmissionGradeRequest request =
        new ExamSubmissionGradeRequest(
            "attempt-1",
            List.of(
                new SubmittedAnswerRequest("q-choice", objectMapper.valueToTree("B")),
                new SubmittedAnswerRequest("q-choice", objectMapper.valueToTree("A"))));

    assertThatThrownBy(() -> service.gradeSubmission(request)).isInstanceOf(CustomException.class);
  }

  @Test
  void gradeSubmissionAllowsEmptySubmittedAnswersAsAllUnanswered() {
    FakeRepository repository = new FakeRepository(snapshot());
    ExamSubmissionGradingService service = service(repository, new FakeRubricPort(List.of()));

    ExamSubmissionGradeResponse response =
        service.gradeSubmission(new ExamSubmissionGradeRequest("attempt-1", List.of()));

    assertThat(response.totalScore()).isEqualByComparingTo("0.0000");
    assertThat(response.maxScore()).isEqualByComparingTo("7.0000");
    assertThat(response.percentage()).isEqualByComparingTo("0.00");
    assertThat(response.results()).extracting("feedback").containsOnly("답안 미제출");
    assertThat(repository.savedResult).isNotNull();
  }

  @Test
  void gradeSubmissionRejectsRubricGradesAboveQuestionMax() {
    FakeRubricPort rubricPort =
        new FakeRubricPort(
            List.of(
                new QuestionGrade(
                    "q-essay",
                    "ko_essay",
                    BigDecimal.valueOf(99),
                    BigDecimal.valueOf(5),
                    false,
                    GradingMode.AI_RUBRIC,
                    "invalid",
                    List.of(),
                    0.1,
                    false)));
    ExamSubmissionGradingService service = service(new FakeRepository(snapshot()), rubricPort);

    ExamSubmissionGradeRequest request =
        new ExamSubmissionGradeRequest(
            "attempt-1",
            List.of(new SubmittedAnswerRequest("q-essay", objectMapper.valueToTree("제출 답안"))));

    assertThatThrownBy(() -> service.gradeSubmission(request)).isInstanceOf(CustomException.class);
  }

  @Test
  void gradeSubmissionDoesNotPersistWhenPublicFeedbackLeaksHiddenAnswer() {
    FakeRepository repository = new FakeRepository(snapshot());
    FakeRubricPort rubricPort =
        new FakeRubricPort(
            List.of(
                new QuestionGrade(
                    "q-essay",
                    "ko_essay",
                    BigDecimal.valueOf(3),
                    BigDecimal.valueOf(5),
                    false,
                    GradingMode.AI_RUBRIC,
                    "정답은 OAuthAuthorizationCodeFlow 입니다.",
                    List.of(new RubricCriterion("근거", BigDecimal.valueOf(3), BigDecimal.valueOf(5), "부분 충족")),
                    0.91,
                    false)));
    ExamSubmissionGradingService service = service(repository, rubricPort);

    ExamSubmissionGradeRequest request =
        new ExamSubmissionGradeRequest(
            "attempt-1",
            List.of(new SubmittedAnswerRequest("q-essay", objectMapper.valueToTree("제출 답안"))));

    assertThatThrownBy(() -> service.gradeSubmission(request)).isInstanceOf(CustomException.class);
    assertThat(repository.savedResult).isNull();
  }

  private ExamSubmissionGradingService service(
      ExamAttemptRepositoryPort repository, ExamForgeRubricGradingPort rubricPort) {
    return new ExamSubmissionGradingService(
        repository,
        rubricPort,
        new DeterministicQuestionScorer(),
        new ExamGradingMapper(),
        new GradingLeakGuard(objectMapper));
  }

  private ExamAttemptSnapshot snapshot() {
    return new ExamAttemptSnapshot(
        "attempt-1",
        "exam-1",
        "sealed-answer-key",
        List.of(choiceQuestion(), essayQuestion()),
        BigDecimal.valueOf(60));
  }

  private ExamQuestion choiceQuestion() {
    return new ExamQuestion(
        "q-choice",
        "draft-choice",
        "ko_multiple_choice_4",
        "HTTP",
        2,
        "remember",
        "HTTP 상태 코드 설명으로 맞는 것은?",
        List.of(
            new QuestionOption("A", "인증 실패", false),
            new QuestionOption("B", "요청 성공", true),
            new QuestionOption("C", "서버 오류", false),
            new QuestionOption("D", "리다이렉트", false)),
        List.of(),
        List.of(),
        List.of(),
        List.of(),
        List.of(),
        null,
        "B",
        "서버 전용 객관식 해설입니다.",
        "server-only-choice-source",
        BigDecimal.valueOf(2),
        "server-only-choice-rationale");
  }

  private ExamQuestion essayQuestion() {
    return new ExamQuestion(
        "q-essay",
        "draft-essay",
        "ko_essay",
        "OAuth",
        5,
        "evaluate",
        "OAuth 흐름을 설명하시오.",
        List.of(),
        List.of(),
        List.of(),
        List.of(),
        List.of(),
        List.of(),
        null,
        "OAuthAuthorizationCodeFlow",
        "서버 전용 서술형 해설입니다.",
        "server-only-essay-source",
        BigDecimal.valueOf(5),
        "server-only-essay-rationale");
  }

  private static final class FakeRepository implements ExamAttemptRepositoryPort {
    private final ExamAttemptSnapshot snapshot;
    private ExamGradeResult savedResult;

    private FakeRepository(ExamAttemptSnapshot snapshot) {
      this.snapshot = snapshot;
    }

    @Override
    public Optional<ExamAttemptSnapshot> findGradingSnapshot(String attemptId) {
      return snapshot.attemptId().equals(attemptId) ? Optional.of(snapshot) : Optional.empty();
    }

    @Override
    public void saveGradingResult(ExamGradeResult result) {
      this.savedResult = result;
    }
  }

  private static final class FakeRubricPort implements ExamForgeRubricGradingPort {
    private final List<QuestionGrade> grades;
    private final List<SubmittedAnswer> lastAnswers = new ArrayList<>();

    private FakeRubricPort(List<QuestionGrade> grades) {
      this.grades = grades;
    }

    @Override
    public List<QuestionGrade> gradeRubricQuestions(
        ExamAttemptSnapshot snapshot, List<SubmittedAnswer> rubricAnswers) {
      lastAnswers.clear();
      lastAnswers.addAll(rubricAnswers);
      return grades;
    }
  }
}
