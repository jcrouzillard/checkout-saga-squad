package com.checkout.order.domain;

import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.common.web.ApiException;
import com.checkout.common.web.ApiException.FieldError;
import com.checkout.order.api.CreateOrderRequest;
import com.checkout.order.api.RequestHasher;
import com.checkout.order.messaging.OrderPayloads.Line;
import com.checkout.order.messaging.OrderPayloads.OrderCanceled;
import com.checkout.order.messaging.OrderPayloads.OrderConfirmed;
import com.checkout.order.messaging.OrderPayloads.OrderCreated;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validator;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.Clock;
import java.time.Instant;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.UUID;

/** Criação de pedidos (POST /orders) com Idempotency-Key + outbox de order.created (api.md §1). */
@Service
public class OrderService {

    private static final Logger log = LoggerFactory.getLogger(OrderService.class);
    private static final Set<String> DELIVERY_TYPES = Set.of("PHYSICAL", "DIGITAL");
    public static final String CURRENCY = "BRL";

    public record CreateResult(OrderRecord order, boolean replayed) {}

    private final OrderRepository repo;
    private final OutboxWriter outbox;
    private final MessageFactory messages;
    private final ObjectMapper mapper;
    private final Validator validator;
    private final TransactionTemplate tx;
    private final Clock clock;

    public OrderService(OrderRepository repo, OutboxWriter outbox, MessageFactory messages, ObjectMapper mapper,
                        Validator validator, TransactionTemplate tx, Clock clock) {
        this.repo = repo;
        this.outbox = outbox;
        this.messages = messages;
        this.mapper = mapper;
        this.validator = validator;
        this.tx = tx;
        this.clock = clock;
    }

    public CreateResult create(String idempotencyKey, JsonNode body, UUID correlationId) {
        if (idempotencyKey == null || idempotencyKey.isBlank() || idempotencyKey.length() > 100) {
            throw ApiException.badRequest("Header Idempotency-Key obrigatório (1–100 caracteres)",
                    List.of(new FieldError("Idempotency-Key", "obrigatório, 1–100 caracteres")));
        }
        if (body == null || !body.isObject()) {
            throw ApiException.badRequest("Corpo deve ser um objeto JSON", List.of());
        }
        String hash = RequestHasher.sha256(body);
        var existing = repo.findByIdempotencyKey(idempotencyKey);
        if (existing.isPresent()) {
            return replay(existing.get(), hash);
        }
        Validated v = validate(body);
        try {
            OrderRecord created = tx.execute(status -> insert(idempotencyKey, hash, v, correlationId));
            return new CreateResult(created, false);
        } catch (DuplicateKeyException race) {
            // Corrida entre duas requisições com a mesma chave: reler e aplicar a regra 200/409.
            return repo.findByIdempotencyKey(idempotencyKey).map(o -> replay(o, hash)).orElseThrow(() -> race);
        }
    }

    private CreateResult replay(OrderRecord o, String hash) {
        if (!o.requestHash().equals(hash)) {
            throw new ApiException(HttpStatus.CONFLICT, "Conflict",
                    "Idempotency-Key já utilizado com um corpo diferente", List.of());
        }
        return new CreateResult(o, true);
    }

    private OrderRecord insert(String key, String hash, Validated v, UUID correlationId) {
        Instant now = Instant.now(clock).truncatedTo(ChronoUnit.MICROS);
        UUID orderId = UUID.randomUUID();
        UUID sagaId = UUID.randomUUID();
        CreateOrderRequest r = v.request();
        boolean physical = "PHYSICAL".equals(r.deliveryType());
        CreateOrderRequest.Address address = physical ? r.shippingAddress() : null;
        OrderRecord o = new OrderRecord(orderId, sagaId, key, hash, r.customerId(), OrderRecord.PENDING,
                r.deliveryType(), v.total(), CURRENCY, toJson(address), null, null, null, null, null, null,
                correlationId, now, now);
        try (var mdc = SagaMdc.of(orderId, sagaId)) {
            repo.insert(o, toJson(v.simulate()), v.lines());
            repo.addHistory(orderId, "ORDER", "CREATED", 1, null, now);
            OrderCreated payload = new OrderCreated(r.customerId(), r.deliveryType(), v.lines(), v.total(), CURRENCY,
                    address, v.simulate(), now);
            MessageEnvelope env = messages.create(com.checkout.common.messaging.Topics.Types.ORDER_CREATED, sagaId,
                    orderId, correlationId, null, payload);
            outbox.publish(Topics.ORDER_EVENTS, env);
            log.info("Pedido criado orderId={} sagaId={} deliveryType={} total={}", orderId, sagaId,
                    r.deliveryType(), v.total());
        }
        return o;
    }

    // ---------------------------------------------------------------- commands (order.confirm / order.cancel)

    /** order.confirm: PENDING → CONFIRMED; já CONFIRMED → re-publica; CANCELED → ERROR + re-publica estado atual. */
    public void confirm(MessageEnvelope cmd, java.util.UUID paymentId, java.util.UUID shipmentId, String tracking) {
        OrderRecord o = repo.lockById(cmd.orderId()).orElse(null);
        if (o == null) {
            log.warn("order.confirm para pedido inexistente orderId={}", cmd.orderId());
            return;
        }
        Instant now = Instant.now(clock);
        switch (o.status()) {
            case OrderRecord.PENDING -> {
                repo.confirm(o.orderId(), paymentId, shipmentId, tracking, now);
                repo.addHistory(o.orderId(), "ORDER", "CONFIRMED", 1, null, now);
                log.info("Pedido confirmado orderId={}", o.orderId());
                publishConfirmed(cmd, paymentId, shipmentId, tracking, now);
            }
            case OrderRecord.CONFIRMED -> publishConfirmed(cmd, o.paymentId(), o.shipmentId(), o.trackingCode(),
                    o.updatedAt());
            default -> {
                log.error("Transição inválida: order.confirm para pedido CANCELED orderId={}; re-publicando estado",
                        o.orderId());
                publishCanceled(cmd, o.cancellationReason(), o.failedStep(), o.cancellationMessage(), o.updatedAt());
            }
        }
    }

    /** order.cancel: PENDING → CANCELED; já CANCELED → re-publica; CONFIRMED → ERROR + re-publica estado atual. */
    public void cancel(MessageEnvelope cmd, String reason, String failedStep, String message) {
        OrderRecord o = repo.lockById(cmd.orderId()).orElse(null);
        if (o == null) {
            log.warn("order.cancel para pedido inexistente orderId={}", cmd.orderId());
            return;
        }
        Instant now = Instant.now(clock);
        switch (o.status()) {
            case OrderRecord.PENDING -> {
                repo.cancel(o.orderId(), reason, failedStep, message, now);
                repo.addHistory(o.orderId(), "ORDER", "CANCELED", 1, reason, now);
                log.info("Pedido cancelado orderId={} reason={} failedStep={}", o.orderId(), reason, failedStep);
                publishCanceled(cmd, reason, failedStep, message, now);
            }
            case OrderRecord.CANCELED -> publishCanceled(cmd, o.cancellationReason(), o.failedStep(),
                    o.cancellationMessage(), o.updatedAt());
            default -> {
                log.error("Transição inválida: order.cancel para pedido CONFIRMED orderId={}; re-publicando estado",
                        o.orderId());
                publishConfirmed(cmd, o.paymentId(), o.shipmentId(), o.trackingCode(), o.updatedAt());
            }
        }
    }

    private void publishConfirmed(MessageEnvelope cmd, UUID paymentId, UUID shipmentId, String tracking, Instant at) {
        outbox.publish(Topics.ORDER_EVENTS, messages.replyTo(cmd, Topics.Types.ORDER_CONFIRMED,
                new OrderConfirmed(OrderRecord.CONFIRMED, paymentId, shipmentId, tracking, at)));
    }

    private void publishCanceled(MessageEnvelope cmd, String reason, String failedStep, String message, Instant at) {
        outbox.publish(Topics.ORDER_EVENTS, messages.replyTo(cmd, Topics.Types.ORDER_CANCELED,
                new OrderCanceled(OrderRecord.CANCELED, reason, failedStep, message, at)));
    }

    // ---------------------------------------------------------------- validação (api.md §1)

    record Validated(CreateOrderRequest request, List<Line> lines, BigDecimal total, Simulate simulate) {}

    Validated validate(JsonNode body) {
        CreateOrderRequest r;
        try {
            r = mapper.treeToValue(body, CreateOrderRequest.class);
        } catch (JsonProcessingException | IllegalArgumentException e) {
            throw ApiException.badRequest("Corpo inválido: tipos de campo incorretos", List.of());
        }
        List<FieldError> errors = new ArrayList<>();
        for (ConstraintViolation<CreateOrderRequest> cv : validator.validate(r)) {
            errors.add(new FieldError(cv.getPropertyPath().toString(), cv.getMessage()));
        }
        if (r.deliveryType() != null && !r.deliveryType().isBlank() && !DELIVERY_TYPES.contains(r.deliveryType())) {
            errors.add(new FieldError("deliveryType", "deve ser PHYSICAL ou DIGITAL"));
        }
        if ("PHYSICAL".equals(r.deliveryType())) {
            CreateOrderRequest.Address a = r.shippingAddress();
            if (a == null) {
                errors.add(new FieldError("shippingAddress", "obrigatório quando deliveryType=PHYSICAL"));
            } else {
                requireText(errors, "shippingAddress.street", a.street());
                requireText(errors, "shippingAddress.number", a.number());
                requireText(errors, "shippingAddress.city", a.city());
                requireText(errors, "shippingAddress.state", a.state());
                requireText(errors, "shippingAddress.zipCode", a.zipCode());
                requireText(errors, "shippingAddress.country", a.country());
            }
        }
        Simulate simulate = parseSimulate(r.simulate(), errors);
        if (!errors.isEmpty()) {
            errors.sort(Comparator.comparing(FieldError::field));
            throw ApiException.badRequest("Requisição inválida", errors);
        }
        List<Line> lines = r.items().stream()
                .map(i -> new Line(i.sku(), i.quantity(), i.unitPrice().setScale(2, RoundingMode.UNNECESSARY)))
                .toList();
        BigDecimal total = lines.stream()
                .map(l -> l.unitPrice().multiply(BigDecimal.valueOf(l.quantity())))
                .reduce(BigDecimal.ZERO, BigDecimal::add)
                .setScale(2, RoundingMode.HALF_UP);
        return new Validated(r, lines, total, simulate);
    }

    private static void requireText(List<FieldError> errors, String field, String value) {
        if (value == null || value.isBlank()) {
            errors.add(new FieldError(field, "obrigatório"));
        }
    }

    private static Simulate parseSimulate(JsonNode node, List<FieldError> errors) {
        if (node == null || node.isNull()) {
            return null;
        }
        if (!node.isObject()) {
            errors.add(new FieldError("simulate", "deve ser um objeto"));
            return null;
        }
        Iterator<Map.Entry<String, JsonNode>> it = node.fields();
        while (it.hasNext()) {
            var e = it.next();
            Set<String> allowed = Simulate.ALLOWED.get(e.getKey());
            if (allowed == null) {
                errors.add(new FieldError("simulate." + e.getKey(), "chave desconhecida"));
            } else if (!e.getValue().isNull() && (!e.getValue().isTextual() || !allowed.contains(e.getValue().asText()))) {
                errors.add(new FieldError("simulate." + e.getKey(), "valor inválido; aceitos: " + allowed));
            }
        }
        Simulate s = new Simulate(text(node, "inventory"), text(node, "payment"), text(node, "shipping"));
        return s.inventory() == null && s.payment() == null && s.shipping() == null ? null : s;
    }

    private static String text(JsonNode node, String field) {
        JsonNode v = node.get(field);
        return v == null || v.isNull() || !v.isTextual() ? null : v.asText();
    }

    private String toJson(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return mapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
