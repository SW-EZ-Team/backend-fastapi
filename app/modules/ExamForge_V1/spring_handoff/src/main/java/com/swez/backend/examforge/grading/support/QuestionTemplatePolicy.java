/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.support;

import java.util.Set;

public class QuestionTemplatePolicy {

  private static final Set<String> CHOICE_TEMPLATES =
      Set.of(
          "ko_multiple_choice_4",
          "ko_multiple_choice_5",
          "us_multiple_choice_4",
          "us_multiple_choice_5",
          "engineer_written",
          "cert_base");
  private static final Set<String> TRUE_FALSE_TEMPLATES = Set.of("ko_true_false", "us_true_false");
  private static final Set<String> SHORT_TEMPLATES = Set.of("ko_short_answer", "us_short_answer");
  private static final Set<String> BLANK_TEMPLATES = Set.of("ko_fill_blank", "us_fill_blank");
  private static final Set<String> ORDER_TEMPLATES = Set.of("ko_ordering", "us_ordering");
  private static final Set<String> MATCH_TEMPLATES = Set.of("ko_matching", "us_matching");
  private static final Set<String> RUBRIC_TEMPLATES =
      Set.of("ko_descriptive", "ko_essay", "us_essay", "engineer_practical");

  public boolean isChoice(String templateId) {
    return CHOICE_TEMPLATES.contains(templateId);
  }

  public boolean isTrueFalse(String templateId) {
    return TRUE_FALSE_TEMPLATES.contains(templateId);
  }

  public boolean isShortAnswer(String templateId) {
    return SHORT_TEMPLATES.contains(templateId);
  }

  public boolean isBlank(String templateId) {
    return BLANK_TEMPLATES.contains(templateId);
  }

  public boolean isOrdering(String templateId) {
    return ORDER_TEMPLATES.contains(templateId);
  }

  public boolean isMatching(String templateId) {
    return MATCH_TEMPLATES.contains(templateId);
  }

  public boolean isRubric(String templateId) {
    return RUBRIC_TEMPLATES.contains(templateId);
  }
}
