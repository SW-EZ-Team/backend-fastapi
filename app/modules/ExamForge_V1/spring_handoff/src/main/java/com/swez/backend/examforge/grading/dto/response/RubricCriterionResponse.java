/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.dto.response;

import io.swagger.v3.oas.annotations.media.Schema;
import java.math.BigDecimal;
import lombok.Builder;

@Builder
@Schema(description = "문항별 루브릭 세부 채점 결과")
public record RubricCriterionResponse(
    @Schema(description = "채점 기준명", example = "개념 정확성")
        String criterion,
    @Schema(description = "취득점", example = "1.5")
        BigDecimal score,
    @Schema(description = "기준별 만점", example = "2.0")
        BigDecimal maxScore,
    @Schema(description = "점수 근거", example = "핵심 용어를 정확히 사용했습니다.")
        String reason) {}
