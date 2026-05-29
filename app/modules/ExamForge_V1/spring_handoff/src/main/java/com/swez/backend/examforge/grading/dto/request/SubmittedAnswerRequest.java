/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.dto.request;

import com.fasterxml.jackson.databind.JsonNode;
import io.swagger.v3.oas.annotations.media.Schema;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;

@Schema(description = "응시자 제출 답안 DTO")
public record SubmittedAnswerRequest(
    @NotBlank
        @Schema(description = "문항 ID", example = "q_0001")
        String questionId,
    @NotNull
        @Schema(description = "답안 payload. 객관식은 문자열, 빈칸/순서형은 배열 또는 객체")
        JsonNode answer) {}
