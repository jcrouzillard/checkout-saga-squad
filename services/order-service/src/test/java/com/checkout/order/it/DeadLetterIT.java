package com.checkout.order.it;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Topics;
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
import org.springframework.kafka.core.KafkaTemplate;

import java.time.Duration;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * D6/ADR-010 §2: mensagem venenosa (JSON inválido) em {@code order.commands} vai para
 * {@code order.commands.DLT} após as tentativas do error handler (common/{@code KafkaCommonConfiguration}),
 * e o consumidor CONTINUA processando mensagens válidas depois — não trava a fila.
 */
class DeadLetterIT extends AbstractIntegrationIT {

    @Autowired
    KafkaTemplate<String, String> kafka;

    @Autowired
    MessageFactory messages;

    @Autowired
    TestRestTemplate rest;

    @Test
    void poisonMessageGoesToDltAndConsumerKeepsProcessingAfterwards() throws Exception {
        String key = "it-dlt-" + UUID.randomUUID();
        String poison = "isto não é json";

        kafka.send(Topics.ORDER_COMMANDS, key, poison).get(10, TimeUnit.SECONDS);

        try (KafkaConsumer<String, String> dlt = newConsumer(Topics.ORDER_COMMANDS + Topics.DLT_SUFFIX)) {
            ConsumerRecord<String, String> rec = awaitRecord(dlt, Duration.ofSeconds(30),
                    r -> key.equals(r.key()) && poison.equals(r.value()));
            assertThat(rec.value()).isEqualTo(poison);
        }

        // O consumidor não travou: um order.confirm válido enviado depois é aplicado normalmente.
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("Idempotency-Key", UUID.randomUUID().toString());
        String body = """
                {"customerId":"it-dlt-order-%s","items":[{"sku":"SKU-IT-004","quantity":1,"unitPrice":10.00}],
                 "deliveryType":"DIGITAL","shippingAddress":null,"simulate":null}
                """.formatted(UUID.randomUUID());
        ResponseEntity<String> created = rest.postForEntity("/orders", new HttpEntity<>(body, headers), String.class);
        UUID orderId = UUID.fromString(MAPPER.readTree(created.getBody()).get("orderId").asText());

        MessageEnvelope confirm = messages.create(UUID.randomUUID(), Topics.Types.ORDER_CONFIRM,
                UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                Map.of("paymentId", UUID.randomUUID(), "shipmentId", UUID.randomUUID(), "trackingCode", "TRACK-IT-2"));
        kafka.send(Topics.ORDER_COMMANDS, orderId.toString(), messages.write(confirm)).get(10, TimeUnit.SECONDS);

        Awaitility.await().atMost(Duration.ofSeconds(20)).untilAsserted(() -> {
            ResponseEntity<String> get = rest.getForEntity("/orders/{id}", String.class, orderId);
            assertThat(MAPPER.readTree(get.getBody()).get("status").asText()).isEqualTo("CONFIRMED");
        });
    }
}
