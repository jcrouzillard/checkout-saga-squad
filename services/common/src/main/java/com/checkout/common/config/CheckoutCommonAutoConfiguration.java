package com.checkout.common.config;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.kafka.KafkaCommonConfiguration;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.outbox.OutboxRelay;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.common.web.CorrelationIdFilter;
import com.checkout.common.web.ProblemDetailsAdvice;
import com.fasterxml.jackson.databind.DeserializationFeature;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.cfg.JsonNodeFeature;
import com.fasterxml.jackson.databind.node.JsonNodeFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.AutoConfiguration;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.boot.autoconfigure.condition.ConditionalOnWebApplication;
import org.springframework.boot.autoconfigure.jackson.Jackson2ObjectMapperBuilderCustomizer;
import org.springframework.boot.autoconfigure.jackson.JacksonAutoConfiguration;
import org.springframework.boot.autoconfigure.jdbc.JdbcClientAutoConfiguration;
import org.springframework.boot.autoconfigure.kafka.KafkaAutoConfiguration;
import org.springframework.boot.autoconfigure.transaction.TransactionAutoConfiguration;
import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.core.Ordered;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.scheduling.annotation.EnableScheduling;
import org.springframework.transaction.support.TransactionTemplate;

import java.time.Clock;

/** Auto-configuração da lib common: basta adicionar a dependência {@code com.checkout:common}. */
@AutoConfiguration(after = {JacksonAutoConfiguration.class, KafkaAutoConfiguration.class,
        JdbcClientAutoConfiguration.class, TransactionAutoConfiguration.class})
@EnableScheduling
@Import(KafkaCommonConfiguration.class)
public class CheckoutCommonAutoConfiguration {

    /** Dinheiro exato: 99.80 continua 99.80 (BigDecimal) ao passar por JsonNode. */
    @Bean
    public Jackson2ObjectMapperBuilderCustomizer checkoutJacksonCustomizer() {
        return builder -> builder
                .featuresToEnable(DeserializationFeature.USE_BIG_DECIMAL_FOR_FLOATS)
                .postConfigurer(om -> {
                    om.setNodeFactory(JsonNodeFactory.withExactBigDecimals(true));
                    om.configure(JsonNodeFeature.STRIP_TRAILING_BIGDECIMAL_ZEROES, false);
                });
    }

    @Bean
    @ConditionalOnMissingBean
    public Clock clock() {
        return Clock.systemUTC();
    }

    @Bean
    @ConditionalOnMissingBean
    public MessageFactory messageFactory(ObjectMapper mapper, Clock clock,
                                         @Value("${spring.application.name:unknown-service}") String source) {
        return new MessageFactory(mapper, source, clock);
    }

    @Bean
    @ConditionalOnMissingBean
    public OutboxWriter outboxWriter(JdbcClient jdbc, MessageFactory messages) {
        return new OutboxWriter(jdbc, messages);
    }

    @Bean
    @ConditionalOnMissingBean
    @ConditionalOnProperty(name = "checkout.outbox.relay-enabled", havingValue = "true", matchIfMissing = true)
    public OutboxRelay outboxRelay(JdbcClient jdbc, KafkaTemplate<String, String> kafka, TransactionTemplate tx,
                                   @Value("${checkout.outbox.batch-size:100}") int batchSize) {
        return new OutboxRelay(jdbc, kafka, tx, batchSize);
    }

    @Bean
    @ConditionalOnMissingBean
    public IdempotencyGuard idempotencyGuard(JdbcClient jdbc,
                                             @Value("${spring.application.name:unknown-service}") String consumer) {
        return new IdempotencyGuard(jdbc, consumer);
    }

    @Bean
    @ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
    @ConditionalOnMissingBean
    public ProblemDetailsAdvice problemDetailsAdvice() {
        return new ProblemDetailsAdvice();
    }

    @Bean
    @ConditionalOnWebApplication(type = ConditionalOnWebApplication.Type.SERVLET)
    public FilterRegistrationBean<CorrelationIdFilter> correlationIdFilter() {
        FilterRegistrationBean<CorrelationIdFilter> reg = new FilterRegistrationBean<>(new CorrelationIdFilter());
        reg.setOrder(Ordered.HIGHEST_PRECEDENCE + 10);
        return reg;
    }
}
