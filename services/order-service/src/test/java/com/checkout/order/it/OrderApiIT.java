package com.checkout.order.it;

import com.fasterxml.jackson.databind.JsonNode;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;

import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * D6/ADR-010 §2: POST /orders (Idempotency-Key: replay e 409), GET /orders/{orderId} — contra o
 * contexto Spring real (Postgres via Testcontainers), sem mocks (docs/architecture/testes.md §2).
 */
class OrderApiIT extends AbstractIntegrationIT {

    @Autowired
    TestRestTemplate rest;

    private static String body(String customerId) {
        return """
                {"customerId":"%s","items":[{"sku":"SKU-IT-001","quantity":1,"unitPrice":10.00}],
                 "deliveryType":"DIGITAL","shippingAddress":null,"simulate":null}
                """.formatted(customerId);
    }

    private static HttpEntity<String> request(String body, String idempotencyKey) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        if (idempotencyKey != null) {
            headers.set("Idempotency-Key", idempotencyKey);
        }
        return new HttpEntity<>(body, headers);
    }

    private UUID orderId(String responseBody) throws Exception {
        JsonNode json = MAPPER.readTree(responseBody);
        return UUID.fromString(json.get("orderId").asText());
    }

    @Test
    void createReturns202WithLocation() {
        ResponseEntity<String> resp = rest.postForEntity("/orders", request(body("it-customer-1"),
                UUID.randomUUID().toString()), String.class);

        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        assertThat(resp.getHeaders().getLocation()).isNotNull();
        assertThat(resp.getHeaders().getLocation().toString()).contains("/orders/");
    }

    @Test
    void sameIdempotencyKeySameBodyReplaysWithSameOrderId() throws Exception {
        String key = UUID.randomUUID().toString();
        String body = body("it-customer-2");

        ResponseEntity<String> first = rest.postForEntity("/orders", request(body, key), String.class);
        assertThat(first.getStatusCode()).isEqualTo(HttpStatus.ACCEPTED);
        UUID firstId = orderId(first.getBody());

        ResponseEntity<String> second = rest.postForEntity("/orders", request(body, key), String.class);
        assertThat(second.getStatusCode()).isEqualTo(HttpStatus.OK);
        assertThat(second.getHeaders().getFirst("Idempotent-Replayed")).isEqualTo("true");
        assertThat(orderId(second.getBody())).isEqualTo(firstId);
    }

    @Test
    void sameIdempotencyKeyDifferentBodyReturns409() {
        String key = UUID.randomUUID().toString();
        rest.postForEntity("/orders", request(body("it-customer-3"), key), String.class);

        ResponseEntity<String> resp = rest.postForEntity("/orders", request(body("it-customer-3-outro"), key),
                String.class);

        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.CONFLICT);
    }

    @Test
    void missingIdempotencyKeyReturns400() {
        ResponseEntity<String> resp = rest.postForEntity("/orders", request(body("it-customer-4"), null),
                String.class);

        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.BAD_REQUEST);
    }

    @Test
    void getReturnsPendingWithCreatedAsFirstHistoryEntry() throws Exception {
        ResponseEntity<String> created = rest.postForEntity("/orders",
                request(body("it-customer-5"), UUID.randomUUID().toString()), String.class);
        UUID id = orderId(created.getBody());

        ResponseEntity<String> got = rest.getForEntity("/orders/{id}", String.class, id);

        assertThat(got.getStatusCode()).isEqualTo(HttpStatus.OK);
        JsonNode json = MAPPER.readTree(got.getBody());
        assertThat(json.get("status").asText()).isEqualTo("PENDING");
        assertThat(json.get("history").get(0).get("status").asText()).isEqualTo("CREATED");
        assertThat(json.get("history").get(0).get("step").asText()).isEqualTo("ORDER");
    }

    @Test
    void getUnknownIdReturns404() {
        ResponseEntity<String> resp = rest.getForEntity("/orders/{id}", String.class, UUID.randomUUID());

        assertThat(resp.getStatusCode()).isEqualTo(HttpStatus.NOT_FOUND);
    }
}
