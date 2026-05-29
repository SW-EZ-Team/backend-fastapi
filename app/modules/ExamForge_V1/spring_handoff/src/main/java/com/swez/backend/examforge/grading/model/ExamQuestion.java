/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;
import java.util.List;

public record ExamQuestion(
    @JsonProperty("question_id") String questionId,
    @JsonProperty("draft_id") String draftId,
    @JsonProperty("template_id") String templateId,
    String topic,
    Integer difficulty,
    @JsonProperty("bloom_level") String bloomLevel,
    String stem,
    List<QuestionOption> options,
    @JsonProperty("matching_pairs") List<MatchingPair> matchingPairs,
    @JsonProperty("ordering_items") List<String> orderingItems,
    @JsonProperty("correct_ordering") List<String> correctOrdering,
    @JsonProperty("blank_positions") List<Integer> blankPositions,
    @JsonProperty("blank_answers") List<String> blankAnswers,
    @JsonProperty("code_snippet") String codeSnippet,
    @JsonProperty("correct_answer") String correctAnswer,
    String explanation,
    @JsonProperty("source_reference") String sourceReference,
    BigDecimal points,
    @JsonProperty("distractor_rationale") String distractorRationale) {

  public BigDecimal pointValue() {
    return points == null ? BigDecimal.ONE : points;
  }
}
