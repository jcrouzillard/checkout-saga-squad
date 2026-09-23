package com.checkout.order.it;

import com.checkout.common.messaging.Topics;
import com.fasterxml.jackson.databind.JsonNode;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.awaitility.Awaitility;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.web.client.TestRestTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.simple.JdbcClient;

import java.time.Duration;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * D6/ADR-010 §2: outbox transacional + relay publicando de verdade no Kafka (ADR-002), sem mockar o
 * relay (docs/architecture/testes.md §2 — "Relay real").
 */
class OutboxRelayIT extends AbstractIntegrationIT {

    @Autowired
    TestRestTemplate rest;

    @Autowired
    JdbcClient jdbc;

    @Test
    void orderCreatedReachesOrderEventsWithFullEnvelopeAndOutboxRowMarkedPublished() throws Exception {
        String customerId = "it-outbox-" + UUID.randomUUID();
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("Idempotency-Key", UUID.randomUUID().toString());
        String body = """
                {"customerId":"%s","items":[{"sku":"SKU-IT-002","quantity":1,"unitPrice":10.00}],
                 "deliveryType":"DIGITAL","shippingAddress":null,"simulate":null}
                """.formatted(customerId);

        ResponseEntity<String> resp = rest.postForEntity("/orders", new HttpEntity<>(body, headers), String.class);
        UUID orderId = UUID.fromString(MAPPER.readTree(resp.getBody()).get("orderId").asText());

        try (KafkaConsumer<String, String> consumer = newConsumer(Topics.ORDER_EVENTS)) {
            ConsumerRecord<String, String> rec = awaitRecord(consumer, Duration.ofSeconds(30),
                    r -> orderId.toString().equals(r.key()));

            assertThat(rec.key()).isEqualTo(orderId.toString());
            JsonNode envelope = MAPPER.readTree(rec.value());
            assertThat(envelope.get("type").asText()).isEqualTo(Topics.Types.ORDER_CREATED);
            assertThat(envelope.get("messageId").asText()).isNotBlank();
            assertThat(envelope.get("sagaId").asText()).isNotBlank();
            assertThat(envelope.get("orderId").asText()).isEqualTo(orderId.toString());
            assertThat(envelope.get("correlationId").asText()).isNotBlank();
            assertThat(envelope.hasNonNull("causationId")).isFalse(); // order.created não tem causa (é o início)

            UUID messageId = UUID.fromString(envelope.get("messageId").asText());
            Awaitility.await().atMost(Duration.ofSeconds(15)).untilAsserted(() -> {
                Long publishedAt = jdbc.sql("SELECT count(*) FROM outbox WHERE message_id = :id AND published_at IS NOT NULL")
                        .param("id", messageId)
                        .query(Long.class)
                        .single();
                assertThat(publishedAt).isEqualTo(1L);
            });
        }
    }
}
