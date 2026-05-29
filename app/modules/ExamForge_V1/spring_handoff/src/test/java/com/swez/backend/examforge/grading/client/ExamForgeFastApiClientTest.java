/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.client;

import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.header;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.swez.backend.examforge.grading.model.ExamAttemptSnapshot;
import com.swez.backend.examforge.grading.model.ExamQuestion;
import com.swez.backend.examforge.grading.model.SubmittedAnswer;
import com.swez.backend.global.exception.CustomException;
import java.math.BigDecimal;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class ExamForgeFastApiClientTest {

  private final ObjectMapper objectMapper = new ObjectMapper();

  @Test
  void wrapsInvalidFastApiResponseContractAsCustomException() {
    RestClient.Builder builder =
        RestClient.builder().baseUrl("http://fastapi").defaultHeader("X-API-Key", "test-key");
    MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    server
        .expect(requestTo("http://fastapi/api/exam-forge/grade-submission"))
        .andExpect(header("X-API-Key", "test-key"))
        .andRespond(
            withSuccess(
                """
                {
                  "attempt_id": "attempt-1",
                  "exam_id": "exam-1",
                  "total_score": 1,
                  "max_score": 5,
                  "percentage": 20,
                  "passed": false,
                  "grading_status": "graded",
                  "graded_at": "2026-05-26T00:00:00Z",
                  "results": [
                    {
                      "question_id": "q-essay",
                      "template_id": "ko_essay",
                      "score": 1,
                      "max_score": 5,
                      "is_correct": false,
                      "grading_mode": "vendor_drift",
                      "feedback": "부분 충족",
                      "rubric_breakdown": [],
                      "confidence": 0.8,
                      "needs_manual_review": false
                    }
                  ]
                }
                """,
                MediaType.APPLICATION_JSON));

    ExamForgeFastApiClient client = new ExamForgeFastApiClient(builder.build());

    assertThatThrownBy(
            () ->
                client.gradeRubricQuestions(
                    snapshot(), List.of(new SubmittedAnswer("q-essay", objectMapper.valueToTree("답안")))))
        .isInstanceOf(CustomException.class);
    server.verify();
  }

  private ExamAttemptSnapshot snapshot() {
    return new ExamAttemptSnapshot(
        "attempt-1",
        "exam-1",
        "sealed-answer-key",
        List.of(
            new ExamQuestion(
                "q-essay",
                "draft-1",
                "ko_essay",
                "topic",
                5,
                "evaluate",
                "stem",
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                List.of(),
                null,
                "OAuthAuthorizationCodeFlow",
                "서버 전용 해설입니다.",
                "server-only-source-reference",
                BigDecimal.valueOf(5),
                "server-only-distractor-rationale")),
        BigDecimal.valueOf(60));
  }
}
