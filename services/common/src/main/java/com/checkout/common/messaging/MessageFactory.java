package com.checkout.common.messaging;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;

import java.time.Clock;
import java.time.Instant;
import java.util.UUID;

/** Cria, serializa e desserializa envelopes. {@code source} = spring.application.name. */
public class MessageFactory {

    private final ObjectMapper mapper;
    private final String source;
    private final Clock clock;

    public MessageFactory(ObjectMapper mapper, String source, Clock clock) {
        this.mapper = mapper;
        this.source = source;
        this.clock = clock;
    }

    public String source() {
        return source;
    }

    /** Nova mensagem com messageId aleatório. */
    public MessageEnvelope create(String type, UUID sagaId, UUID orderId, UUID correlationId, UUID causationId,
                                  Object payload) {
        return create(UUID.randomUUID(), type, sagaId, orderId, correlationId, causationId, payload);
    }

    /** Mensagem com messageId explícito (ex.: retry de comando reutiliza o MESMO messageId). */
    public MessageEnvelope create(UUID messageId, String type, UUID sagaId, UUID orderId, UUID correlationId,
                                  UUID causationId, Object payload) {
        return new MessageEnvelope(messageId, type, MessageEnvelope.CURRENT_VERSION, source, Instant.now(clock),
                sagaId, orderId, correlationId, causationId, toTree(payload));
    }

    /** Resposta/evento causado por {@code cause}: novo messageId, causationId = cause.messageId. */
    public MessageEnvelope replyTo(MessageEnvelope cause, String type, Object payload) {
        return create(type, cause.sagaId(), cause.orderId(), cause.correlationId(), cause.messageId(), payload);
    }

    public JsonNode toTree(Object payload) {
        if (payload == null) {
            return mapper.createObjectNode();
        }
        return payload instanceof JsonNode n ? n : mapper.valueToTree(payload);
    }

    public <T> T payload(MessageEnvelope envelope, Class<T> type) {
        try {
            return mapper.treeToValue(envelope.payload(), type);
        } catch (JsonProcessingException e) {
            throw new MalformedMessageException("Payload inválido para " + envelope.type() + ": " + e.getOriginalMessage(), e);
        }
    }

    /** Desserializa o valor Kafka; JSON inválido → {@link MalformedMessageException} (vai para DLT após 3 tentativas). */
    public MessageEnvelope read(String json) {
        try {
            MessageEnvelope env = mapper.readValue(json, MessageEnvelope.class);
            if (env.messageId() == null || env.type() == null || env.orderId() == null) {
                throw new MalformedMessageException("Envelope sem messageId/type/orderId");
            }
            return env;
        } catch (JsonProcessingException e) {
            throw new MalformedMessageException("Envelope JSON inválido: " + e.getOriginalMessage(), e);
        }
    }

    public String write(MessageEnvelope envelope) {
        try {
            return mapper.writeValueAsString(envelope);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("Falha ao serializar envelope", e);
        }
    }
}
