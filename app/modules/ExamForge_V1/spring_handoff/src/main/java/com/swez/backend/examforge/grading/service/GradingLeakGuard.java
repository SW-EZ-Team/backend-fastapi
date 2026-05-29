/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.swez.backend.examforge.grading.exception.ExamForgeGradingErrorCode;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.MatchingPair;
import com.swez.backend.examforge.grading.model.QuestionOption;
import com.swez.backend.global.exception.CustomException;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Component;

@Slf4j
@Component
@RequiredArgsConstructor
public class GradingLeakGuard {

  private static final List<String> BLOCKED_TOKENS =
      List.of(
          "correctAnswer",
          "correct_answer",
          "explanation",
          "sourceReference",
          "source_reference",
          "answerKeySeal",
          "answer_key_seal",
          "answersHtml",
          "answers_html");
  private static final Set<String> PUBLIC_TEXT_FIELDS = Set.of("feedback", "reason", "criterion", "message");
  private static final Set<String> REVEAL_CONTEXT_TOKENS =
      Set.of(
          "답",
          "답:",
          "답안",
          "정답",
          "답은",
          "모범답안",
          "기준답안",
          "해설",
          "선택",
          "선택지",
          "보기",
          "골라",
          "고르",
          "맞",
          "옳",
          "correct",
          "correctanswer",
          "correct answer",
          "answer",
          "answer is",
          "selected",
          "choice",
          "option",
          "should be");

  private final ObjectMapper objectMapper;

  public void assertPublicResponseSafe(Object response) {
    assertPublicResponseSafe(response, null);
  }

  public void assertPublicResponseSafe(Object response, ExamAttemptSnapshot snapshot) {
    String serialized = serialize(response);
    JsonNode root = parse(serialized);
    assertBlockedFieldNames(root);
    if (snapshot == null || snapshot.questions() == null) {
      return;
    }
    List<String> publicTexts = publicTextValues(root);
    hiddenValues(snapshot).forEach(value -> assertHiddenValueAbsent(publicTexts, value));
  }

  private String serialize(Object response) {
    try {
      return objectMapper.writeValueAsString(response);
    } catch (JsonProcessingException e) {
      log.error("[GradingLeakGuard] response serialization failed", e);
      throw new CustomException(ExamForgeGradingErrorCode.SENSITIVE_RESPONSE_BLOCKED);
    }
  }

  private JsonNode parse(String serialized) {
    try {
      return objectMapper.readTree(serialized);
    } catch (JsonProcessingException e) {
      log.error("[GradingLeakGuard] response parse failed", e);
      throw new CustomException(ExamForgeGradingErrorCode.SENSITIVE_RESPONSE_BLOCKED);
    }
  }

  private void assertBlockedFieldNames(JsonNode node) {
    if (node == null || node.isNull()) {
      return;
    }
    if (node.isObject()) {
      Iterator<Map.Entry<String, JsonNode>> fields = node.fields();
      while (fields.hasNext()) {
        Map.Entry<String, JsonNode> field = fields.next();
        if (BLOCKED_TOKENS.contains(field.getKey())) {
          log.error("[GradingLeakGuard] blocked sensitive public response field: {}", field.getKey());
          throw new CustomException(ExamForgeGradingErrorCode.SENSITIVE_RESPONSE_BLOCKED);
        }
        assertBlockedFieldNames(field.getValue());
      }
      return;
    }
    if (node.isArray()) {
      node.forEach(this::assertBlockedFieldNames);
    }
  }

  private List<String> publicTextValues(JsonNode node) {
    List<String> result = new ArrayList<>();
    collectPublicTextValues(node, "", result);
    return result;
  }

  private void collectPublicTextValues(JsonNode node, String fieldName, List<String> result) {
    if (node == null || node.isNull()) {
      return;
    }
    if (node.isTextual() && PUBLIC_TEXT_FIELDS.contains(fieldName)) {
      result.add(node.asText(""));
      return;
    }
    if (node.isObject()) {
      Iterator<Map.Entry<String, JsonNode>> fields = node.fields();
      while (fields.hasNext()) {
        Map.Entry<String, JsonNode> field = fields.next();
        collectPublicTextValues(field.getValue(), field.getKey(), result);
      }
      return;
    }
    if (node.isArray()) {
      node.forEach(item -> collectPublicTextValues(item, fieldName, result));
    }
  }

  private List<String> hiddenValues(ExamAttemptSnapshot snapshot) {
    List<String> result = new ArrayList<>();
    for (ExamQuestion question : snapshot.questions()) {
      addHiddenValue(result, question.correctAnswer());
      addHiddenValue(result, question.explanation());
      addHiddenValue(result, question.sourceReference());
      addHiddenValue(result, question.distractorRationale());
      addHiddenValues(result, question.correctOrdering());
      addHiddenValues(result, question.blankAnswers());
      if (question.matchingPairs() != null) {
        for (MatchingPair pair : question.matchingPairs()) {
          addHiddenValue(result, pair.right());
        }
      }
      if (question.options() != null) {
        for (QuestionOption option : question.options()) {
          if (option.correct()) {
            addHiddenValue(result, option.label());
            addHiddenValue(result, option.text());
          }
        }
      }
    }
    return result;
  }

  private void addHiddenValues(List<String> result, List<String> values) {
    if (values == null) {
      return;
    }
    values.forEach(value -> addHiddenValue(result, value));
  }

  private void addHiddenValue(List<String> result, String value) {
    String compactHidden = compact(value);
    if (compactHidden.isBlank()) {
      return;
    }
    result.add(value);
  }

  private void assertHiddenValueAbsent(List<String> publicTexts, String hiddenValue) {
    String compactHidden = compact(hiddenValue);
    if (compactHidden.isBlank()) {
      return;
    }
    for (String publicText : publicTexts) {
      String compactPublicText = compact(publicText);
      if (compactPublicText.contains(compactHidden) && shouldBlockHiddenValue(compactHidden, compactPublicText)) {
        log.error("[GradingLeakGuard] blocked hidden grading value in public response");
        throw new CustomException(ExamForgeGradingErrorCode.SENSITIVE_RESPONSE_BLOCKED);
      }
    }
  }

  private boolean shouldBlockHiddenValue(String compactHidden, String compactPublicText) {
    if (compactHidden.length() >= 3) {
      return true;
    }
    return REVEAL_CONTEXT_TOKENS.stream().map(this::compact).anyMatch(compactPublicText::contains);
  }

  private String compact(String value) {
    if (value == null) {
      return "";
    }
    return value.replaceAll("\\s+", "").toLowerCase();
  }
}
