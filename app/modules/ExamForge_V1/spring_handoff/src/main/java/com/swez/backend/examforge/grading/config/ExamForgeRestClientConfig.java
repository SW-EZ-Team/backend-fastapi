/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.config;

import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.boot.http.client.ClientHttpRequestFactoryBuilder;
import org.springframework.boot.http.client.ClientHttpRequestFactorySettings;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.client.RestClient;

@Configuration
@EnableConfigurationProperties(ExamForgeFastApiProperties.class)
@ConditionalOnProperty(prefix = "examforge.fastapi", name = {"base-url", "api-key"})
public class ExamForgeRestClientConfig {

  @Bean
  public RestClient examForgeRestClient(
      RestClient.Builder builder, ExamForgeFastApiProperties properties) {
    ClientHttpRequestFactorySettings settings =
        ClientHttpRequestFactorySettings.defaults()
            .withConnectTimeout(properties.connectTimeout())
            .withReadTimeout(properties.readTimeout());

    return builder
        .baseUrl(properties.baseUrl())
        .defaultHeader("X-API-Key", properties.apiKey())
        .requestFactory(ClientHttpRequestFactoryBuilder.detect().build(settings))
        .build();
  }
}
