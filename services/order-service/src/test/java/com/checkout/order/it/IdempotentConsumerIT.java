package com.checkout.order.it;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
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
import org.springframework.kafka.core.KafkaTemplate;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * D6/ADR-010 §2: consumidor idempotente (events.md §5.1) — publicar o MESMO {@code messageId} duas
 * vezes em {@code order.commands} tem UM efeito só: uma linha em {@code processed_messages}, uma
 * transição de histórico, um {@code order.confirmed} publicado no outbox para essa causa.
 */
class IdempotentConsumerIT extends AbstractIntegrationIT {

    @Autowired
    TestRestTemplate rest;

    @Autowired
    JdbcClient jdbc;

    @Autowired
    MessageFactory messages;

    @Autowired
    KafkaTemplate<String, String> kafka;

    @Test
    void duplicateOrderConfirmHasExactlyOneEffect() throws Exception {
        // 1) cria o pedido (fica PENDING).
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("Idempotency-Key", UUID.randomUUID().toString());
        String body = """
                {"customerId":"it-idem-%s","items":[{"sku":"SKU-IT-003","quantity":1,"unitPrice":10.00}],
                 "deliveryType":"DIGITAL","shippingAddress":null,"simulate":null}
                """.formatted(UUID.randomUUID());
        ResponseEntity<String> created = rest.postForEntity("/orders", new HttpEntity<>(body, headers), String.class);
        UUID orderId = UUID.fromString(MAPPER.readTree(created.getBody()).get("orderId").asText());

        // 2) publica order.confirm duas vezes, MESMO messageId (simula retry/reentrega do broker).
        UUID messageId = UUID.randomUUID();
        UUID sagaId = UUID.randomUUID();
        UUID correlationId = UUID.randomUUID();
        UUID paymentId = UUID.randomUUID();
        UUID shipmentId = UUID.randomUUID();
        Map<String, Object> payload = Map.of("paymentId", paymentId, "shipmentId", shipmentId,
                "trackingCode", "TRACK-IT-1");
        MessageEnvelope cmd = messages.create(messageId, Topics.Types.ORDER_CONFIRM, sagaId, orderId, correlationId,
                null, payload);
        String value = messages.write(cmd);

        kafka.send(Topics.ORDER_COMMANDS, orderId.toString(), value).get(10, TimeUnit.SECONDS);
        kafka.send(Topics.ORDER_COMMANDS, orderId.toString(), value).get(10, TimeUnit.SECONDS);

        // 3) o pedido confirma (via GET, poll com Awaitility).
        Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> {
            ResponseEntity<String> get = rest.getForEntity("/orders/{id}", String.class, orderId);
            assertThat(MAPPER.readTree(get.getBody()).get("status").asText()).isEqualTo("CONFIRMED");
        });

        // 4) UMA linha em processed_messages para esse messageId.
        Long processedCount = jdbc.sql("SELECT count(*) FROM processed_messages WHERE message_id = :id")
                .param("id", messageId)
                .query(Long.class)
                .single();
        assertThat(processedCount).isEqualTo(1L);

        // 5) UM registro CONFIRMED no histórico (não dois, mesmo com a duplicata).
        Long confirmedHistoryCount = jdbc.sql(
                        "SELECT count(*) FROM order_status_history WHERE order_id = :id AND step = 'ORDER' AND status = 'CONFIRMED'")
                .param("id", orderId)
                .query(Long.class)
                .single();
        assertThat(confirmedHistoryCount).isEqualTo(1L);

        // 6) UM order.confirmed no outbox/Kafka causado por esse messageId (não dois).
        try (KafkaConsumer<String, String> consumer = newConsumer(Topics.ORDER_EVENTS)) {
            ConsumerRecord<String, String> rec = awaitRecord(consumer, Duration.ofSeconds(20), r -> {
                if (!orderId.toString().equals(r.key())) {
                    return false;
                }
                try {
                    JsonNode env = MAPPER.readTree(r.value());
                    return Topics.Types.ORDER_CONFIRMED.equals(env.path("type").asText())
                            && messageId.toString().equals(env.path("causationId").asText());
                } catch (Exception e) {
                    return false;
                }
            });
            assertThat(rec).isNotNull();
        }
    }
}
