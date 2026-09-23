package com.checkout.common.kafka;

import com.checkout.common.messaging.MalformedMessageException;
import com.checkout.common.messaging.Topics;
import org.apache.kafka.clients.admin.NewTopic;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnMissingBean;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.kafka.config.TopicBuilder;
import org.springframework.kafka.core.KafkaAdmin;
import org.springframework.kafka.core.KafkaTemplate;
import org.springframework.kafka.listener.CommonErrorHandler;
import org.springframework.kafka.listener.DeadLetterPublishingRecoverer;
import org.springframework.kafka.listener.DefaultErrorHandler;
import org.springframework.kafka.support.serializer.DeserializationException;
import org.springframework.util.backoff.ExponentialBackOff;
import org.springframework.util.backoff.FixedBackOff;

/**
 * Kafka comum (events.md §1 e §5): tópicos com 3 partições; error handler:
 * <ul>
 *   <li>mensagem venenosa ({@link MalformedMessageException}/desserialização) → 3 tentativas → {@code <tópico>.DLT};</li>
 *   <li>qualquer outra exceção (ex.: banco fora) → retry exponencial sem limite (nunca perde a mensagem).</li>
 * </ul>
 * enable.auto.commit=false e AckMode RECORD vêm dos defaults de {@code CommonEnvironmentPostProcessor};
 * com listener {@code @Transactional} o offset é confirmado após o commit do banco.
 */
@Configuration(proxyBeanMethods = false)
public class KafkaCommonConfiguration {

    private static final Logger log = LoggerFactory.getLogger(KafkaCommonConfiguration.class);

    @Bean
    @ConditionalOnProperty(name = "checkout.kafka.create-topics", havingValue = "true", matchIfMissing = true)
    public KafkaAdmin.NewTopics checkoutTopics() {
        return new KafkaAdmin.NewTopics(Topics.ALL.stream()
                .map(t -> TopicBuilder.name(t).partitions(Topics.PARTITIONS).replicas(1).build())
                .toArray(NewTopic[]::new));
    }

    @Bean
    @ConditionalOnMissingBean(CommonErrorHandler.class)
    public DefaultErrorHandler kafkaErrorHandler(KafkaTemplate<String, String> template) {
        DefaultErrorHandler handler = new DefaultErrorHandler(new DeadLetterPublishingRecoverer(template),
                new FixedBackOff(500L, 2L));
        ExponentialBackOff transientBackOff = new ExponentialBackOff(500L, 2.0);
        transientBackOff.setMaxInterval(10_000L);
        handler.setBackOffFunction((record, ex) -> isPoison(ex) ? null : transientBackOff);
        handler.setRetryListeners((record, ex, attempt) -> log.warn(
                "Falha ao processar mensagem topic={} partition={} offset={} tentativa={}: {}",
                record.topic(), record.partition(), record.offset(), attempt, rootMessage(ex)));
        return handler;
    }

    static boolean isPoison(Throwable ex) {
        for (Throwable t = ex; t != null; t = t.getCause()) {
            if (t instanceof MalformedMessageException || t instanceof DeserializationException) {
                return true;
            }
        }
        return false;
    }

    private static String rootMessage(Throwable ex) {
        Throwable t = ex;
        while (t.getCause() != null && t.getCause() != t) {
            t = t.getCause();
        }
        return t.toString();
    }
}
