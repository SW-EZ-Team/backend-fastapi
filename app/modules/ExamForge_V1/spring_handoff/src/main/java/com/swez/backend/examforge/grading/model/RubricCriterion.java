/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.model;

import com.fasterxml.jackson.annotation.JsonProperty;
import java.math.BigDecimal;

public record RubricCriterion(
    String criterion,
    BigDecimal score,
    @JsonProperty("max_score") BigDecimal maxScore,
    String reason) {}
