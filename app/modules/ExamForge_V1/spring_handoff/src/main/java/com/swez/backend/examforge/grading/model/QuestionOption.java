/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.model;

import com.fasterxml.jackson.annotation.JsonProperty;

public record QuestionOption(
    String label,
    String text,
    @JsonProperty("is_correct") boolean correct) {}
