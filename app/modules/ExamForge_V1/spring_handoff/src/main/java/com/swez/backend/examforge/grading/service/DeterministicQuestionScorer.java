/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.GradingMode;
import com.swez.backend.examforge.grading.model.MatchingPair;
import com.swez.backend.examforge.grading.model.QuestionGrade;
import com.swez.backend.examforge.grading.model.QuestionOption;
import com.swez.backend.examforge.grading.model.RubricCriterion;
import com.swez.backend.examforge.grading.support.AnswerNormalizer;
import com.swez.backend.examforge.grading.support.QuestionTemplatePolicy;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.springframework.stereotype.Component;

@Component
public class DeterministicQuestionScorer {

  private final AnswerNormalizer normalizer = new AnswerNormalizer();
  private final QuestionTemplatePolicy policy = new QuestionTemplatePolicy();

  public QuestionGrade score(ExamQuestion question, JsonNode answer) {
    String templateId = question.templateId();
    if (policy.isChoice(templateId)) {
      return scoreChoice(question, answer);
    }
    if (policy.isTrueFalse(templateId)) {
      return scoreTrueFalse(question, answer);
    }
    if (policy.isBlank(templateId)) {
      return scoreBlank(question, answer);
    }
    if (policy.isOrdering(templateId)) {
      return scoreOrdering(question, answer);
    }
    if (policy.isMatching(templateId)) {
      return scoreMatching(question, answer);
    }
    return scoreExact(question, answer);
  }

  public QuestionGrade unanswered(ExamQuestion question) {
    return result(question, BigDecimal.ZERO, "답안 미제출", List.of());
  }

  public QuestionGrade scoreExact(ExamQuestion question, JsonNode answer) {
    String candidate = normalizer.compactText(normalizer.scalarText(answer));
    boolean correct = normalizer.acceptedVariants(question.correctAnswer()).contains(candidate);
    BigDecimal score = correct ? points(question) : BigDecimal.ZERO;
    String reason = correct ? "허용 답안과 일치" : "허용 답안과 불일치";
    return result(question, score, reason, List.of(criterion("정답 일치", score, points(question), reason)));
  }

  private QuestionGrade scoreChoice(ExamQuestion question, JsonNode answer) {
    String candidate = normalizer.compactText(normalizer.scalarText(answer));
    List<String> accepted = new ArrayList<>(normalizer.acceptedVariants(question.correctAnswer()));
    if (question.options() != null) {
      for (QuestionOption option : question.options()) {
        if (option.correct()) {
          accepted.add(normalizer.compactText(option.label()));
          accepted.add(normalizer.compactText(option.text()));
        }
      }
    }
    boolean correct = accepted.contains(candidate);
    BigDecimal score = correct ? points(question) : BigDecimal.ZERO;
    String reason = correct ? "정답 보기 선택" : "오답 보기 선택";
    return result(question, score, reason, List.of(criterion("보기 선택", score, points(question), reason)));
  }

  private QuestionGrade scoreTrueFalse(ExamQuestion question, JsonNode answer) {
    String candidate = boolToken(normalizer.scalarText(answer));
    boolean correct =
        normalizer.acceptedVariants(question.correctAnswer()).stream()
            .map(this::boolToken)
            .anyMatch(candidate::equals);
    BigDecimal score = correct ? points(question) : BigDecimal.ZERO;
    String reason = correct ? "참거짓 판정 일치" : "참거짓 판정 불일치";
    return result(question, score, reason, List.of(criterion("참거짓", score, points(question), reason)));
  }

  private QuestionGrade scoreBlank(ExamQuestion question, JsonNode answer) {
    List<String> expected =
        question.blankAnswers() == null || question.blankAnswers().isEmpty()
            ? normalizer.splitSequenceText(question.correctAnswer())
            : question.blankAnswers();
    if (expected.isEmpty()) {
      return scoreExact(question, answer);
    }
    return scoreSequence(question, normalizer.sequenceValues(answer), expected, "빈칸", "빈칸 위치별 채점");
  }

  private QuestionGrade scoreOrdering(ExamQuestion question, JsonNode answer) {
    List<String> expected =
        question.correctOrdering() == null || question.correctOrdering().isEmpty()
            ? normalizer.splitSequenceText(question.correctAnswer())
            : question.correctOrdering();
    if (expected.isEmpty()) {
      return scoreExact(question, answer);
    }
    return scoreSequence(question, normalizer.sequenceValues(answer), expected, "순서", "순서 위치별 채점");
  }

  private QuestionGrade scoreMatching(ExamQuestion question, JsonNode answer) {
    List<MatchingPair> expected = question.matchingPairs() == null ? List.of() : question.matchingPairs();
    if (expected.isEmpty()) {
      return scoreExact(question, answer);
    }
    Map<String, String> submitted = normalizer.mappingValues(answer);
    BigDecimal unit = points(question).divide(BigDecimal.valueOf(expected.size()), 8, RoundingMode.HALF_UP);
    BigDecimal total = BigDecimal.ZERO;
    List<RubricCriterion> criteria = new ArrayList<>();
    for (MatchingPair pair : expected) {
      String candidate = normalizer.compactText(submitted.getOrDefault(normalizer.normalizeText(pair.left()), ""));
      boolean correct = candidate.equals(normalizer.compactText(pair.right()));
      BigDecimal itemScore = correct ? unit : BigDecimal.ZERO;
      total = total.add(itemScore);
      criteria.add(criterion(pair.left(), itemScore, unit, correct ? "연결 일치" : "연결 불일치"));
    }
    return result(question, total, "연결 항목별 채점", criteria);
  }

  private QuestionGrade scoreSequence(
      ExamQuestion question, List<String> submitted, List<String> expected, String label, String feedback) {
    BigDecimal unit = points(question).divide(BigDecimal.valueOf(expected.size()), 8, RoundingMode.HALF_UP);
    BigDecimal total = BigDecimal.ZERO;
    List<RubricCriterion> criteria = new ArrayList<>();
    for (int index = 0; index < expected.size(); index++) {
      boolean correct =
          index < submitted.size()
              && normalizer.acceptedVariants(expected.get(index)).contains(normalizer.compactText(submitted.get(index)));
      BigDecimal itemScore = correct ? unit : BigDecimal.ZERO;
      total = total.add(itemScore);
      criteria.add(criterion(label + " " + (index + 1), itemScore, unit, correct ? "일치" : "불일치"));
    }
    return result(question, total, feedback, criteria);
  }

  private QuestionGrade result(
      ExamQuestion question, BigDecimal score, String feedback, List<RubricCriterion> criteria) {
    BigDecimal maxScore = points(question);
    BigDecimal finalScore = score.max(BigDecimal.ZERO).min(maxScore).setScale(4, RoundingMode.HALF_UP);
    return new QuestionGrade(
        question.questionId(),
        question.templateId(),
        finalScore,
        maxScore.setScale(4, RoundingMode.HALF_UP),
        finalScore.compareTo(maxScore) >= 0,
        GradingMode.DETERMINISTIC,
        feedback,
        criteria,
        1.0,
        false);
  }

  private RubricCriterion criterion(String name, BigDecimal score, BigDecimal maxScore, String reason) {
    return new RubricCriterion(name, score.setScale(4, RoundingMode.HALF_UP), maxScore.setScale(4, RoundingMode.HALF_UP), reason);
  }

  private BigDecimal points(ExamQuestion question) {
    return question.pointValue().max(new BigDecimal("0.01"));
  }

  private String boolToken(String value) {
    String normalized = normalizer.compactText(value);
    if (List.of("o", "true", "t", "yes", "y", "참", "맞음", "옳음").contains(normalized)) {
      return "true";
    }
    if (List.of("x", "false", "f", "no", "n", "거짓", "틀림", "그름").contains(normalized)) {
      return "false";
    }
    return normalized;
  }
}
