package com.checkout.inventory.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.inventory.domain.InventoryRepository;
import com.checkout.inventory.domain.Item;
import com.checkout.inventory.domain.Reservation;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Clock;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class InventoryCommandHandlerTest {

    private final ObjectMapper mapper = JsonMapper.builder().findAndAddModules().build();
    private final MessageFactory messages = new MessageFactory(mapper, "saga-orchestrator", Clock.systemUTC());
    private InventoryRepository repo;
    private IdempotencyGuard idempotency;
    private OutboxWriter outbox;
    private InventoryCommandHandler handler;
    private final UUID orderId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        repo = mock(InventoryRepository.class);
        idempotency = mock(IdempotencyGuard.class);
        outbox = mock(OutboxWriter.class);
        when(idempotency.tryMarkProcessed(any())).thenReturn(true);
        handler = new InventoryCommandHandler(repo, idempotency, outbox, messages);
    }

    private MessageEnvelope reserveCmd(Simulate simulate) {
        return messages.create(Topics.Types.INVENTORY_RESERVE, UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                new InventoryMessages.ReserveCommand(List.of(new Item("SKU-BOOK-001", 2)), simulate));
    }

    private MessageEnvelope releaseCmd() {
        return messages.create(Topics.Types.INVENTORY_RELEASE, UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                new InventoryMessages.ReleaseCommand("PAYMENT_DECLINED"));
    }

    private MessageEnvelope published() {
        ArgumentCaptor<MessageEnvelope> captor = ArgumentCaptor.forClass(MessageEnvelope.class);
        verify(outbox).publish(eq(Topics.INVENTORY_EVENTS), captor.capture());
        return captor.getValue();
    }

    @Test
    void reservaTudoOuNadaEPublicaReserved() {
        MessageEnvelope cmd = reserveCmd(null);
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.lockAvailable(any())).thenReturn(Map.of("SKU-BOOK-001", 1000));
        when(repo.reserveStock("SKU-BOOK-001", 2)).thenReturn(true);
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(cmd);

        verify(repo).reserveStock("SKU-BOOK-001", 2);
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.INVENTORY_RESERVED);
        assertThat(reply.causationId()).isEqualTo(cmd.messageId());
        assertThat(reply.orderId()).isEqualTo(orderId);
        assertThat(reply.payload().get("reservationId").isNull()).isFalse();
        assertThat(reply.payload().get("items").get(0).get("sku").asText()).isEqualTo("SKU-BOOK-001");
    }

    @Test
    void comandoDuplicadoNaoReexecutaERepublicaAPartirDoEstado() {
        UUID reservationId = UUID.randomUUID();
        MessageEnvelope cmd = reserveCmd(null);
        when(idempotency.tryMarkProcessed(cmd.messageId())).thenReturn(false);
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.of(
                Reservation.reserved(orderId, reservationId, List.of(new Item("SKU-BOOK-001", 2)))));
        when(repo.incrementAttempts(orderId)).thenReturn(2);

        handler.handle(cmd);

        verify(repo, never()).reserveStock(anyString(), anyInt());
        verify(repo, never()).insertReservation(any());
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.INVENTORY_RESERVED);
        assertThat(reply.payload().get("reservationId").asText()).isEqualTo(reservationId.toString());
        assertThat(reply.causationId()).isEqualTo(cmd.messageId());
    }

    @Test
    void simulateTimeoutReservaDeFatoMasNaoResponde() {
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.lockAvailable(any())).thenReturn(Map.of("SKU-BOOK-001", 1000));
        when(repo.reserveStock("SKU-BOOK-001", 2)).thenReturn(true);
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(reserveCmd(new Simulate("TIMEOUT", null, null)));

        verify(repo).reserveStock("SKU-BOOK-001", 2);
        verify(outbox, never()).publish(anyString(), any());
    }

    @Test
    void simulateOutOfStockRejeitaSemReservar() {
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.availableOf(any())).thenReturn(Map.of("SKU-BOOK-001", 1000));
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(reserveCmd(new Simulate("OUT_OF_STOCK", null, null)));

        verify(repo, never()).lockAvailable(any());
        verify(repo, never()).reserveStock(anyString(), anyInt());
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.INVENTORY_REJECTED);
        assertThat(reply.payload().get("reason").asText()).isEqualTo("OUT_OF_STOCK");
    }

    @Test
    void releaseSemReservaGravaTombstoneEAcaoPosteriorResponde_ALREADY_COMPENSATED() {
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.empty());
        handler.handle(releaseCmd());

        ArgumentCaptor<Reservation> saved = ArgumentCaptor.forClass(Reservation.class);
        verify(repo).insertReservation(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(Reservation.RELEASED);
        assertThat(saved.getValue().noop()).isTrue();
        MessageEnvelope released = published();
        assertThat(released.type()).isEqualTo(Topics.Types.INVENTORY_RELEASED);
        assertThat(released.payload().get("noop").asBoolean()).isTrue();
        assertThat(released.payload().get("reservationId").isNull()).isTrue();

        // reserve tardio chega depois do tombstone → falha sem efeito
        outbox = mock(OutboxWriter.class);
        handler = new InventoryCommandHandler(repo, idempotency, outbox, messages);
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.of(saved.getValue()));
        handler.handle(reserveCmd(new Simulate("TIMEOUT", null, null)));

        verify(repo, never()).reserveStock(anyString(), anyInt());
        MessageEnvelope rejected = published();
        assertThat(rejected.type()).isEqualTo(Topics.Types.INVENTORY_REJECTED);
        assertThat(rejected.payload().get("reason").asText()).isEqualTo("ALREADY_COMPENSATED");
    }

    @Test
    void releaseDevolveEstoqueDaReservaReal() {
        UUID reservationId = UUID.randomUUID();
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.of(
                Reservation.reserved(orderId, reservationId, List.of(new Item("SKU-BOOK-001", 2)))));

        handler.handle(releaseCmd());

        verify(repo).releaseStock("SKU-BOOK-001", 2);
        verify(repo).markReleased(orderId);
        MessageEnvelope reply = published();
        assertThat(reply.payload().get("reservationId").asText()).isEqualTo(reservationId.toString());
        assertThat(reply.payload().get("noop").asBoolean()).isFalse();
    }

    @Test
    void releaseDuplicadoNaoDevolveEstoqueDuasVezes() {
        UUID reservationId = UUID.randomUUID();
        when(repo.findReservationForUpdate(orderId)).thenReturn(Optional.of(new Reservation(orderId, reservationId,
                Reservation.RELEASED, List.of(new Item("SKU-BOOK-001", 2)), false, null, null, null, 1)));

        handler.handle(releaseCmd());

        verify(repo, never()).releaseStock(anyString(), anyInt());
        assertThat(published().payload().get("noop").asBoolean()).isFalse();
    }
}
