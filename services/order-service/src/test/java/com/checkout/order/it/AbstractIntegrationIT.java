package com.checkout.order.it;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.apache.kafka.clients.consumer.ConsumerConfig;
import org.apache.kafka.clients.consumer.ConsumerRecord;
import org.apache.kafka.clients.consumer.KafkaConsumer;
import org.apache.kafka.common.serialization.StringDeserializer;
import org.awaitility.Awaitility;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.testcontainers.service.connection.ServiceConnection;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.kafka.KafkaContainer;
import org.testcontainers.utility.DockerImageName;

import java.time.Duration;
import java.util.List;
import java.util.Properties;
import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.Predicate;

import static org.assertj.core.api.Assertions.assertThat;

/**
 * Base dos testes de integração do order-service (D6, ADR-010): Spring Boot completo (contexto real,
 * Flyway, JDBC, Kafka) contra Postgres e Kafka REAIS via Testcontainers — não mocks. Sem Docker
 * disponível, {@code mvn verify} falha nesta classe (evidência honesta; {@code -DskipITs} é a saída
 * explícita).
 *
 * <p><b>Padrão "singleton container"</b> (correção do G2-D6, 2º ciclo): os contêineres são
 * {@code static}, iniciados uma única vez num bloco {@code static} e NUNCA parados explicitamente —
 * de propósito, sem {@code @Testcontainers}/{@code @Container}. Essas anotações fazem a extensão do
 * JUnit encerrar os contêineres ao fim de CADA classe de teste, mas o contexto Spring (cacheado pelo
 * {@code SpringBootTest} entre classes com a mesma configuração) continua com o {@code DataSource}/
 * {@code KafkaTemplate} apontando para as portas antigas — daí as conexões recusadas a partir da 2ª
 * classe. {@code @ServiceConnection} continua funcionando sem {@code @Container}: é o Spring Boot,
 * não a extensão do JUnit, quem lê essa anotação para configurar `spring.datasource.*`/
 * `spring.kafka.*`. O JVM encerra os contêineres no shutdown (Ryuk).
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
abstract class AbstractIntegrationIT {

    static final ObjectMapper MAPPER = new ObjectMapper().findAndRegisterModules();

    @ServiceConnection
    static final PostgreSQLContainer<?> POSTGRES = new PostgreSQLContainer<>("postgres:16-alpine");

    @ServiceConnection
    static final KafkaContainer KAFKA = new KafkaContainer(DockerImageName.parse("apache/kafka-native:3.8.0"));

    static {
        POSTGRES.start();
        KAFKA.start();
    }

    /** Consumidor de teste puro (fora do contexto Spring), group aleatório, lê desde o início. */
    static KafkaConsumer<String, String> newConsumer(String... topics) {
        Properties props = new Properties();
        props.put(ConsumerConfig.BOOTSTRAP_SERVERS_CONFIG, KAFKA.getBootstrapServers());
        props.put(ConsumerConfig.GROUP_ID_CONFIG, "it-" + UUID.randomUUID());
        props.put(ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest");
        props.put(ConsumerConfig.KEY_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        props.put(ConsumerConfig.VALUE_DESERIALIZER_CLASS_CONFIG, StringDeserializer.class.getName());
        KafkaConsumer<String, String> consumer = new KafkaConsumer<>(props);
        consumer.subscribe(List.of(topics));
        return consumer;
    }

    /**
     * Espera (Awaitility, nunca {@code Thread.sleep}) até {@code match} casar com algum registro lido
     * do consumidor. Cada avaliação da condição faz UM poll curto — o consumidor só é usado pela
     * thread de poll da Awaitility (sempre a mesma), respeitando a regra de single-thread do Kafka.
     */
    static ConsumerRecord<String, String> awaitRecord(KafkaConsumer<String, String> consumer, Duration timeout,
                                                       Predicate<ConsumerRecord<String, String>> match) {
        AtomicReference<ConsumerRecord<String, String>> found = new AtomicReference<>();
        Awaitility.await().atMost(timeout).pollInterval(Duration.ofMillis(200)).untilAsserted(() -> {
            if (found.get() == null) {
                for (ConsumerRecord<String, String> r : consumer.poll(Duration.ofMillis(200))) {
                    if (match.test(r)) {
                        found.set(r);
                        break;
                    }
                }
            }
            assertThat(found.get()).as("registro esperado em %s", (Object[]) consumer.assignment().toArray())
                    .isNotNull();
        });
        return found.get();
    }
}
