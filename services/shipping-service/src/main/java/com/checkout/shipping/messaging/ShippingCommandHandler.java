package com.checkout.shipping.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.shipping.domain.Carrier;
import com.checkout.shipping.domain.ReplyPolicy;
import com.checkout.shipping.domain.Shipment;
import com.checkout.shipping.domain.ShipmentRepository;
import com.checkout.shipping.messaging.ShippingMessages.CancelCommand;
import com.checkout.shipping.messaging.ShippingMessages.Canceled;
import com.checkout.shipping.messaging.ShippingMessages.CreateCommand;
import com.checkout.shipping.messaging.ShippingMessages.Created;
import com.checkout.shipping.messaging.ShippingMessages.Failed;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Clock;
import java.util.Optional;
import java.util.UUID;

/**
 * Processa {@code shipment.create} / {@code shipment.cancel} numa única transação:
 * dedupe ({@code processed_messages}) + efeito + resposta no outbox (events.md §5, ADR-002).
 * <p>Comando duplicado ou nova criação para o mesmo pedido NÃO reexecuta: a resposta é re-publicada a partir do
 * estado persistido em {@code shipments}.
 */
@Service
public class ShippingCommandHandler {

    private static final Logger log = LoggerFactory.getLogger(ShippingCommandHandler.class);

    private final ShipmentRepository repo;
    private final IdempotencyGuard idempotency;
    private final OutboxWriter outbox;
    private final MessageFactory messages;
    private final Clock clock;

    public ShippingCommandHandler(ShipmentRepository repo, IdempotencyGuard idempotency, OutboxWriter outbox,
                                  MessageFactory messages, Clock clock) {
        this.repo = repo;
        this.idempotency = idempotency;
        this.outbox = outbox;
        this.messages = messages;
        this.clock = clock;
    }

    @Transactional
    public void handle(MessageEnvelope cmd) {
        try (var mdc = SagaMdc.of(cmd)) {
            boolean first = idempotency.tryMarkProcessed(cmd.messageId());
            switch (cmd.type()) {
                case Topics.Types.SHIPMENT_CREATE -> create(cmd, first);
                case Topics.Types.SHIPMENT_CANCEL -> cancel(cmd, first);
                default -> log.warn("Tipo desconhecido ignorado em {}: {}", Topics.SHIPPING_COMMANDS, cmd.type());
            }
        }
    }

    // ------------------------------------------------------------------ shipment.create (ação)

    private void create(MessageEnvelope cmd, boolean first) {
        CreateCommand p = messages.payload(cmd, CreateCommand.class);
        String mode = simulateMode(p);
        UUID orderId = cmd.orderId();

        Optional<Shipment> existing = repo.findForUpdate(orderId);
        if (existing.isPresent() && existing.get().isCanceled()) {
            log.info("shipment.create após cancelamento (noop={}) → shipment.failed ALREADY_COMPENSATED",
                    existing.get().noop());
            publish(cmd, Topics.Types.SHIPMENT_FAILED,
                    new Failed(Carrier.ALREADY_COMPENSATED, "Envio já cancelado/compensado para este pedido"));
            return;
        }

        Shipment shipment;
        if (existing.isPresent()) {
            shipment = existing.get();
            log.info("shipment.create {} para pedido já processado (status={}); re-publicando resposta do estado",
                    first ? "novo" : "duplicado", shipment.status());
        } else {
            shipment = Carrier.create(orderId, p.address(), p.items(), mode, clock);
            repo.insert(shipment);
            log.info("Envio {} shipmentId={} trackingCode={} reason={}{}", shipment.status(), shipment.shipmentId(),
                    shipment.trackingCode(), shipment.reason(), mode != null ? " (simulate.shipping=" + mode + ")" : "");
        }

        int attempts = repo.incrementAttempts(orderId);
        if (!ReplyPolicy.shouldReply(mode, attempts)) {
            log.warn("simulate.shipping={} → resposta suprimida (tentativa {})", mode, attempts);
            return;
        }
        if (shipment.isCreated()) {
            publish(cmd, Topics.Types.SHIPMENT_CREATED, new Created(shipment.shipmentId(), shipment.trackingCode(),
                    shipment.carrier(), shipment.estimatedDeliveryDate()));
        } else {
            publish(cmd, Topics.Types.SHIPMENT_FAILED, new Failed(shipment.reason(), shipment.message()));
        }
    }

    // ------------------------------------------------------------------ shipment.cancel (compensação)

    /** Compensação: sempre executa (simulate nunca se aplica) e sempre responde a partir do estado. */
    private void cancel(MessageEnvelope cmd, boolean first) {
        CancelCommand p = messages.payload(cmd, CancelCommand.class);
        UUID orderId = cmd.orderId();
        Optional<Shipment> existing = repo.findForUpdate(orderId);

        if (existing.isEmpty()) {
            repo.insert(Shipment.tombstone(orderId));
            log.info("shipment.cancel sem envio (reason={}) → tombstone CANCELED noop=true", p.reason());
            publish(cmd, Topics.Types.SHIPMENT_CANCELED, new Canceled(null, true));
            return;
        }

        Shipment s = existing.get();
        switch (s.status()) {
            case Shipment.CREATED -> {
                repo.markCanceled(orderId);
                log.info("Envio cancelado shipmentId={} (reason={})", s.shipmentId(), p.reason());
                publish(cmd, Topics.Types.SHIPMENT_CANCELED, new Canceled(s.shipmentId(), false));
            }
            case Shipment.CANCELED -> {
                log.info("shipment.cancel {} para envio já cancelado; re-publicando", first ? "novo" : "duplicado");
                publish(cmd, Topics.Types.SHIPMENT_CANCELED, new Canceled(s.shipmentId(), s.noop()));
            }
            default -> { // FAILED: nenhum envio foi criado → cancelamento é no-op
                log.info("shipment.cancel para envio FAILED → noop");
                publish(cmd, Topics.Types.SHIPMENT_CANCELED, new Canceled(null, true));
            }
        }
    }

    // ------------------------------------------------------------------ helpers

    private static String simulateMode(CreateCommand p) {
        String mode = p.simulateMode();
        if (mode != null && !Simulate.ALLOWED.get("shipping").contains(mode)) {
            log.warn("simulate.shipping desconhecido ignorado: {}", mode);
            return null;
        }
        return mode;
    }

    private void publish(MessageEnvelope cmd, String type, Object payload) {
        outbox.publish(Topics.SHIPPING_EVENTS, messages.replyTo(cmd, type, payload));
    }
}
