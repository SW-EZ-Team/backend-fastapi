/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.service;

import static org.assertj.core.api.Assertions.assertThatCode;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.fasterxml.jackson.databind.json.JsonMapper;
import com.swez.backend.examforge.grading.dto.response.ExamSubmissionGradeResponse;
import com.swez.backend.examforge.grading.dto.response.QuestionGradeResponse;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.GradingMode;
import com.swez.backend.examforge.grading.model.GradingStatus;
import com.swez.backend.global.exception.CustomException;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;

class GradingLeakGuardTest {

  private final GradingLeakGuard leakGuard = new GradingLeakGuard(JsonMapper.builder().findAndAddModules().build());

  @Test
  void allowsPublicGradeResponseWithoutHiddenValues() {
    ExamSubmissionGradeResponse response =
        response("풀이 방향은 부분적으로 맞지만 핵심 조건 설명이 부족합니다.");

    assertThatCode(() -> leakGuard.assertPublicResponseSafe(response, snapshot()))
        .doesNotThrowAnyException();
  }

  @Test
  void blocksSensitiveFieldNamesInPublicResponse() {
    assertThatThrownBy(
            () -> leakGuard.assertPublicResponseSafe(java.util.Map.of("answerKeySeal", "sealed-value")))
        .isInstanceOf(CustomException.class);
  }

  @Test
  void blocksHiddenAnswerValuesInFeedback() {
    ExamSubmissionGradeResponse response =
        response("정답은 OAuthAuthorizationCodeFlow 이므로 감점했습니다.");

    assertThatThrownBy(() -> leakGuard.assertPublicResponseSafe(response, snapshot()))
        .isInstanceOf(CustomException.class);
  }

  @ParameterizedTest
  @ValueSource(strings = {"정답은 B입니다.", "답: B", "B를 선택해야 합니다.", "선택지 B가 맞습니다."})
  void blocksShortAnswerValuesWhenFeedbackRevealsAnswerContext(String feedback) {
    ExamSubmissionGradeResponse response = response(feedback);

    assertThatThrownBy(() -> leakGuard.assertPublicResponseSafe(response, choiceSnapshot()))
        .isInstanceOf(CustomException.class);
  }

  @Test
  void blocksStructuredAnswerValuesInFeedback() {
    ExamSubmissionGradeResponse response = response("404 값을 써야 하는 빈칸입니다.");

    assertThatThrownBy(() -> leakGuard.assertPublicResponseSafe(response, blankSnapshot()))
        .isInstanceOf(CustomException.class);
  }

  private ExamSubmissionGradeResponse response(String feedback) {
    return ExamSubmissionGradeResponse.builder()
        .attemptId("attempt-1")
        .examId("exam-1")
        .totalScore(BigDecimal.ONE)
        .maxScore(BigDecimal.TEN)
        .percentage(BigDecimal.TEN)
        .passed(false)
        .gradingStatus(GradingStatus.GRADED)
        .gradedAt(OffsetDateTime.now())
        .results(
            List.of(
                QuestionGradeResponse.builder()
                    .questionId("q-essay")
                    .templateId("ko_essay")
                    .score(BigDecimal.ONE)
                    .maxScore(BigDecimal.TEN)
                    .correct(false)
                    .gradingMode(GradingMode.AI_RUBRIC)
                    .feedback(feedback)
                    .rubricBreakdown(List.of())
                    .confidence(0.8)
                    .needsManualReview(false)
                    .build()))
        .build();
  }

  private ExamAttemptSnapshot snapshot() {
    return new ExamAttemptSnapshot(
        "attempt-1",
        "exam-1",
        "sealed-answer-key",
        List.of(
            new ExamQuestion(
                "q-essay",
                "draft-1",
                "ko_essay",
                "topic",
                4,
                "evaluate",
                "stem",
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                null,
                "OAuthAuthorizationCodeFlow",
                "서버 전용 해설입니다.",
                "server-only-source-reference",
                BigDecimal.TEN,
                "server-only-distractor-rationale")),
        BigDecimal.valueOf(60));
  }

  private ExamAttemptSnapshot choiceSnapshot() {
    return new ExamAttemptSnapshot(
        "attempt-choice",
        "exam-choice",
        "sealed-answer-key",
        List.of(
            new ExamQuestion(
                "q-choice",
                "draft-1",
                "ko_multiple_choice_4",
                "topic",
                2,
                "remember",
                "stem",
                List.of(
                    new com.swez.backend.examforge.grading.model.QuestionOption("A", "오답", false),
                    new com.swez.backend.examforge.grading.model.QuestionOption("B", "정답 보기", true)),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                null,
                "B",
                "서버 전용 해설입니다.",
                "server-only-source-reference",
                BigDecimal.TEN,
                "server-only-distractor-rationale")),
        BigDecimal.valueOf(60));
  }

  private ExamAttemptSnapshot blankSnapshot() {
    return new ExamAttemptSnapshot(
        "attempt-blank",
        "exam-blank",
        "sealed-answer-key",
        List.of(
            new ExamQuestion(
                "q-blank",
                "draft-1",
                "ko_fill_blank",
                "topic",
                2,
                "remember",
                "stem",
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of("HTTP", "404"),
                null,
                "HTTP,404",
                "서버 전용 해설입니다.",
                "server-only-source-reference",
                BigDecimal.TEN,
                "server-only-distractor-rationale")),
        BigDecimal.valueOf(60));
  }
}
