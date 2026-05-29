/*
 * Copyright (c) EZ TEAM
 */
package com.swez.backend.examforge.grading.support;

import com.fasterxml.jackson.databind.JsonNode;
import java.text.Normalizer;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

public class AnswerNormalizer {

  private static final Set<String> META_KEYS =
      Set.of("answer", "value", "text", "selected", "choice", "response");
  private static final Pattern SPACES = Pattern.compile("\\s+");
  private static final Pattern NON_WORD = Pattern.compile("[\\W_]+", Pattern.UNICODE_CHARACTER_CLASS);

  public String scalarText(JsonNode value) {
    if (value == null || value.isNull()) {
      return "";
    }
    if (value.isObject()) {
      for (String key : META_KEYS) {
        JsonNode nested = value.get(key);
        if (nested != null) {
          return scalarText(nested);
        }
      }
      return value.toString();
    }
    if (value.isArray()) {
      return value.isEmpty() ? "" : scalarText(value.get(0));
    }
    return value.asText("");
  }

  public List<String> sequenceValues(JsonNode value) {
    if (value == null || value.isNull()) {
      return List.of();
    }
    if (value.isArray()) {
      return arrayValues(value);
    }
    if (value.isObject()) {
      for (String key : List.of("answers", "values", "blanks", "order", "sequence", "items")) {
        JsonNode nested = value.get(key);
        if (nested != null && nested.isArray()) {
          return arrayValues(nested);
        }
      }
      return iterableFields(value).entrySet().stream()
          .sorted(Map.Entry.comparingByKey())
          .map(entry -> scalarText(entry.getValue()))
          .toList();
    }
    return splitSequenceText(scalarText(value));
  }

  private List<String> arrayValues(JsonNode array) {
    List<String> result = new ArrayList<>();
    array.forEach(item -> result.add(scalarText(item)));
    return result;
  }

  public Map<String, String> mappingValues(JsonNode value) {
    if (value == null || value.isNull()) {
      return Map.of();
    }
    if (value.isObject()) {
      JsonNode pairs = value.get("pairs");
      if (pairs != null) {
        return mappingValues(pairs);
      }
      Map<String, String> result = new LinkedHashMap<>();
      iterableFields(value).forEach((key, raw) -> {
        if (!META_KEYS.contains(key) && !"pairs".equals(key)) {
          result.put(normalizeText(key), scalarText(raw));
        }
      });
      return result;
    }
    if (value.isArray()) {
      Map<String, String> result = new LinkedHashMap<>();
      value.forEach(item -> {
        if (item.isObject()) {
          JsonNode left = firstPresent(item, "left", "from", "key");
          JsonNode right = firstPresent(item, "right", "to", "value");
          if (left != null && right != null) {
            result.put(normalizeText(left.asText()), scalarText(right));
          }
        }
      });
      return result;
    }
    return mappingFromText(scalarText(value));
  }

  public String normalizeText(String value) {
    String text = value == null ? "" : value.trim().toLowerCase(Locale.ROOT);
    return SPACES.matcher(Normalizer.normalize(text, Normalizer.Form.NFKC)).replaceAll(" ");
  }

  public String compactText(String value) {
    return NON_WORD.matcher(normalizeText(value)).replaceAll("");
  }

  public Set<String> acceptedVariants(String text) {
    List<String> variants = List.of(text == null ? "" : text);
    for (String separator : List.of("|", "/", ";", ",", "\n", " 또는 ", " 혹은 ")) {
      variants =
          variants.stream()
              .flatMap(item -> Arrays.stream(item.split(Pattern.quote(separator))))
              .toList();
    }
    return variants.stream().map(this::compactText).filter(item -> !item.isBlank()).collect(Collectors.toSet());
  }

  public List<String> splitSequenceText(String text) {
    if (text == null || text.isBlank()) {
      return List.of();
    }
    return Arrays.stream(text.split("[,;\\n>]+"))
        .map(String::trim)
        .filter(item -> !item.isBlank())
        .toList();
  }

  private Map<String, JsonNode> iterableFields(JsonNode value) {
    Map<String, JsonNode> result = new LinkedHashMap<>();
    value.fields().forEachRemaining(entry -> result.put(entry.getKey(), entry.getValue()));
    return result;
  }

  private Map<String, String> mappingFromText(String text) {
    Map<String, String> result = new LinkedHashMap<>();
    for (String pair : splitSequenceText(text)) {
      for (String separator : List.of("->", "=>", ":", "=", "-")) {
        if (pair.contains(separator)) {
          String[] parts = pair.split(Pattern.quote(separator), 2);
          result.put(normalizeText(parts[0]), parts[1].trim());
          break;
        }
      }
    }
    return result;
  }

  private JsonNode firstPresent(JsonNode value, String... keys) {
    for (String key : keys) {
      JsonNode node = value.get(key);
      if (node != null) {
        return node;
      }
    }
    return null;
  }
}
