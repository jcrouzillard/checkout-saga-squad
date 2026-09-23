package com.checkout.inventory.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MalformedMessageException;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.observability.SagaMdc;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.inventory.domain.InventoryRepository;
import com.checkout.inventory.domain.Item;
import com.checkout.inventory.domain.Rejection;
import com.checkout.inventory.domain.ReplyPolicy;
import com.checkout.inventory.domain.Reservation;
import com.checkout.inventory.domain.StockAllocator;
import com.checkout.inventory.messaging.InventoryMessages.Rejected;
import com.checkout.inventory.messaging.InventoryMessages.ReleaseCommand;
import com.checkout.inventory.messaging.InventoryMessages.Released;
import com.checkout.inventory.messaging.InventoryMessages.ReserveCommand;
import com.checkout.inventory.messaging.InventoryMessages.Reserved;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.Map;
import java.util.Optional;
import java.util.SortedMap;
import java.util.UUID;

/**
 * Processa {@code inventory.reserve} / {@code inventory.release} numa única transação:
 * dedupe ({@code processed_messages}) + efeito + resposta no outbox (events.md §5, ADR-002).
 * <p>Comando duplicado (retry com o mesmo messageId) ou nova ação para o mesmo pedido NÃO reexecuta: a resposta é
 * re-publicada a partir do estado persistido em {@code reservations}.
 */
@Service
public class InventoryCommandHandler {

    private static final Logger log = LoggerFactory.getLogger(InventoryCommandHandler.class);

    private final InventoryRepository repo;
    private final IdempotencyGuard idempotency;
    private final OutboxWriter outbox;
    private final MessageFactory messages;

    public InventoryCommandHandler(InventoryRepository repo, IdempotencyGuard idempotency, OutboxWriter outbox,
                                   MessageFactory messages) {
        this.repo = repo;
        this.idempotency = idempotency;
        this.outbox = outbox;
        this.messages = messages;
    }

    @Transactional
    public void handle(MessageEnvelope cmd) {
        try (var mdc = SagaMdc.of(cmd)) {
            boolean first = idempotency.tryMarkProcessed(cmd.messageId());
            switch (cmd.type()) {
                case Topics.Types.INVENTORY_RESERVE -> reserve(cmd, first);
                case Topics.Types.INVENTORY_RELEASE -> release(cmd, first);
                default -> log.warn("Tipo desconhecido ignorado em {}: {}", Topics.INVENTORY_COMMANDS, cmd.type());
            }
        }
    }

    // ------------------------------------------------------------------ inventory.reserve (ação)

    private void reserve(MessageEnvelope cmd, boolean first) {
        ReserveCommand p = messages.payload(cmd, ReserveCommand.class);
        String mode = simulateMode(p);
        UUID orderId = cmd.orderId();

        Optional<Reservation> existing = repo.findReservationForUpdate(orderId);
        if (existing.isPresent() && existing.get().isReleased()) {
            // Tombstone/compensação já aplicada (events.md §5.4): falha sem efeito. Simulação não se aplica.
            log.info("inventory.reserve após compensação (noop={}) → inventory.rejected ALREADY_COMPENSATED",
                    existing.get().noop());
            publish(cmd, Topics.Types.INVENTORY_REJECTED, rejected(Rejection.alreadyCompensated()));
            return;
        }

        Reservation reservation;
        if (existing.isPresent()) {
            reservation = existing.get();
            log.info("inventory.reserve {} para pedido já processado (status={}); re-publicando resposta do estado",
                    first ? "novo" : "duplicado", reservation.status());
        } else {
            reservation = execute(orderId, p, mode);
        }

        int attempts = repo.incrementAttempts(orderId);
        if (!ReplyPolicy.shouldReply(mode, attempts)) {
            log.warn("simulate.inventory={} → resposta suprimida (tentativa {})", mode, attempts);
            return;
        }
        if (reservation.isReserved()) {
            publish(cmd, Topics.Types.INVENTORY_RESERVED, new Reserved(reservation.reservationId(), reservation.items()));
        } else {
            publish(cmd, Topics.Types.INVENTORY_REJECTED, rejected(reservation.rejection()));
        }
    }

    /** Executa a reserva tudo-ou-nada (ou a rejeição simulada) e persiste o resultado. */
    private Reservation execute(UUID orderId, ReserveCommand p, String mode) {
        SortedMap<String, Integer> requested;
        try {
            requested = StockAllocator.normalize(p.items());
        } catch (IllegalArgumentException e) {
            throw new MalformedMessageException(e.getMessage(), e);
        }

        if (Simulate.OUT_OF_STOCK.equals(mode)) {
            Map<String, Integer> available = repo.availableOf(requested.keySet());
            Reservation r = Reservation.rejected(orderId, StockAllocator.toItems(requested),
                    Rejection.outOfStock(StockAllocator.simulatedDetails(requested, available)));
            repo.insertReservation(r);
            log.info("simulate.inventory=OUT_OF_STOCK → rejeitado sem reservar");
            return r;
        }

        Map<String, Integer> available = repo.lockAvailable(requested.keySet());   // FOR UPDATE, ordem de SKU
        Optional<Rejection> rejection = StockAllocator.check(requested, available);
        if (rejection.isPresent()) {
            Reservation r = Reservation.rejected(orderId, StockAllocator.toItems(requested), rejection.get());
            repo.insertReservation(r);
            log.info("Reserva rejeitada: reason={} details={}", rejection.get().reason(), rejection.get().details());
            return r;
        }

        requested.forEach((sku, qty) -> {
            if (!repo.reserveStock(sku, qty)) {
                // Impossível com as linhas travadas; aborta a transação inteira (tudo-ou-nada).
                throw new IllegalStateException("Saldo insuficiente ao debitar " + sku + " apesar do lock");
            }
        });
        Reservation r = Reservation.reserved(orderId, UUID.randomUUID(), StockAllocator.toItems(requested));
        repo.insertReservation(r);
        log.info("Estoque reservado reservationId={} items={}{}", r.reservationId(), r.items(),
                mode != null ? " (simulate.inventory=" + mode + ")" : "");
        return r;
    }

    // ------------------------------------------------------------------ inventory.release (compensação)

    /** Compensação: sempre executa (simulate nunca se aplica) e sempre responde a partir do estado. */
    private void release(MessageEnvelope cmd, boolean first) {
        ReleaseCommand p = messages.payload(cmd, ReleaseCommand.class);
        UUID orderId = cmd.orderId();
        Optional<Reservation> existing = repo.findReservationForUpdate(orderId);

        if (existing.isEmpty()) {
            repo.insertReservation(Reservation.tombstone(orderId));
            log.info("inventory.release sem reserva (reason={}) → tombstone RELEASED noop=true", p.reason());
            publish(cmd, Topics.Types.INVENTORY_RELEASED, new Released(null, true));
            return;
        }

        Reservation r = existing.get();
        switch (r.status()) {
            case Reservation.RESERVED -> {
                for (Item item : r.items()) {          // itens já persistidos em ordem de SKU
                    repo.releaseStock(item.sku(), item.quantity());
                }
                repo.markReleased(orderId);
                log.info("Reserva liberada reservationId={} (reason={})", r.reservationId(), p.reason());
                publish(cmd, Topics.Types.INVENTORY_RELEASED, new Released(r.reservationId(), false));
            }
            case Reservation.RELEASED -> {
                log.info("inventory.release {} para reserva já liberada; re-publicando", first ? "novo" : "duplicado");
                publish(cmd, Topics.Types.INVENTORY_RELEASED, new Released(r.reservationId(), r.noop()));
            }
            default -> { // REJECTED: nada foi reservado → liberação é no-op
                log.info("inventory.release para reserva REJECTED → noop");
                publish(cmd, Topics.Types.INVENTORY_RELEASED, new Released(null, true));
            }
        }
    }

    // ------------------------------------------------------------------ helpers

    private static String simulateMode(ReserveCommand p) {
        String mode = p.simulateMode();
        if (mode != null && !Simulate.ALLOWED.get("inventory").contains(mode)) {
            log.warn("simulate.inventory desconhecido ignorado: {}", mode);
            return null;
        }
        return mode;
    }

    private static Rejected rejected(Rejection r) {
        return new Rejected(r.reason(), r.message(), r.details());
    }

    private void publish(MessageEnvelope cmd, String type, Object payload) {
        outbox.publish(Topics.INVENTORY_EVENTS, messages.replyTo(cmd, type, payload));
    }
}
