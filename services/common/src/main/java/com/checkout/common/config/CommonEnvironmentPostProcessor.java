package com.checkout.common.config;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.env.EnvironmentPostProcessor;
import org.springframework.core.env.ConfigurableEnvironment;
import org.springframework.core.env.MapPropertySource;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * Defaults de MENOR precedência para todos os serviços (qualquer application.yml/env var sobrescreve).
 * Centraliza: Kafka (ack após commit, idempotência do producer), Flyway (locations), Actuator/Micrometer e
 * logs estruturados (docs/observability.md), outbox (api.md §5).
 */
public class CommonEnvironmentPostProcessor implements EnvironmentPostProcessor {

    public static final String SOURCE_NAME = "checkoutCommonDefaults";

    @Override
    public void postProcessEnvironment(ConfigurableEnvironment env, SpringApplication application) {
        Map<String, Object> d = new LinkedHashMap<>();
        // Kafka — events.md §5.6/§5.7
        d.put("spring.kafka.consumer.group-id", "${spring.application.name}");
        d.put("spring.kafka.consumer.enable-auto-commit", "false");
        d.put("spring.kafka.consumer.auto-offset-reset", "earliest");
        d.put("spring.kafka.consumer.key-deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
        d.put("spring.kafka.consumer.value-deserializer", "org.apache.kafka.common.serialization.StringDeserializer");
        d.put("spring.kafka.producer.key-serializer", "org.apache.kafka.common.serialization.StringSerializer");
        d.put("spring.kafka.producer.value-serializer", "org.apache.kafka.common.serialization.StringSerializer");
        d.put("spring.kafka.producer.acks", "all");
        d.put("spring.kafka.producer.properties.enable.idempotence", "true");
        d.put("spring.kafka.listener.ack-mode", "record");
        // Flyway — migração comum (V0.1) + migrações do serviço (V1__, V2__...) em db/migration
        d.put("spring.flyway.locations", "classpath:db/common,classpath:db/migration");
        // Observabilidade — docs/observability.md §1/§2
        d.put("management.endpoints.web.exposure.include", "health,info,prometheus");
        d.put("management.metrics.distribution.percentiles-histogram.saga.step.duration", "true");
        d.put("management.metrics.tags.application", "${spring.application.name}");
        d.put("logging.structured.format.console", "ecs");
        // Outbox — api.md §5
        d.put("checkout.outbox.poll-interval-ms", "${OUTBOX_POLL_INTERVAL_MS:200}");
        d.put("checkout.outbox.batch-size", "${OUTBOX_BATCH_SIZE:100}");
        // Relay + schedulers do serviço não disputam a mesma thread
        d.put("spring.task.scheduling.pool.size", "4");
        env.getPropertySources().addLast(new MapPropertySource(SOURCE_NAME, d));
    }
}
