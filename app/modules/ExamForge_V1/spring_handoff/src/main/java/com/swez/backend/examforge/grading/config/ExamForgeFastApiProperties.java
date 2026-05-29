/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.config;

import jakarta.validation.constraints.NotBlank;
import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

@Validated
@ConfigurationProperties(prefix = "examforge.fastapi")
public record ExamForgeFastApiProperties(
    @NotBlank String baseUrl,
    @NotBlank String apiKey,
    Duration connectTimeout,
    Duration readTimeout) {

  public ExamForgeFastApiProperties {
    if (connectTimeout == null) {
      connectTimeout = Duration.ofSeconds(3);
    }
    if (readTimeout == null) {
      readTimeout = Duration.ofSeconds(120);
    }
  }
}
