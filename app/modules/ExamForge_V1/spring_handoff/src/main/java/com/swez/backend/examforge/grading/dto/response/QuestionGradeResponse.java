/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.dto.response;

import com.swez.backend.examforge.grading.model.GradingMode;
import io.swagger.v3.oas.annotations.media.Schema;
import java.math.BigDecimal;
import java.util.List;
import lombok.Builder;

@Builder
@Schema(description = "문항별 공개 채점 결과")
public record QuestionGradeResponse(
    @Schema(description = "문항 ID", example = "q_0001")
        String questionId,
    @Schema(description = "문항 템플릿 ID", example = "ko_multiple_choice_5")
        String templateId,
    @Schema(description = "취득점", example = "2.0")
        BigDecimal score,
    @Schema(description = "문항 만점", example = "2.0")
        BigDecimal maxScore,
    @Schema(description = "정답 여부", example = "true")
        boolean correct,
    @Schema(description = "채점 방식", example = "DETERMINISTIC")
        GradingMode gradingMode,
    @Schema(description = "응시자 공개 피드백", example = "정답 보기 선택")
        String feedback,
    @Schema(description = "루브릭 세부 결과. 객관식은 비어 있을 수 있음")
        List<RubricCriterionResponse> rubricBreakdown,
    @Schema(description = "AI 채점 신뢰도", example = "1.0")
        double confidence,
    @Schema(description = "수동 검토 필요 여부", example = "false")
        boolean needsManualReview) {}
