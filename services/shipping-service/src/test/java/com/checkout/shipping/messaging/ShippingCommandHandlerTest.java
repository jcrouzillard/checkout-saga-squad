package com.checkout.shipping.messaging;

import com.checkout.common.idempotency.IdempotencyGuard;
import com.checkout.common.messaging.MessageEnvelope;
import com.checkout.common.messaging.MessageFactory;
import com.checkout.common.messaging.Simulate;
import com.checkout.common.messaging.Topics;
import com.checkout.common.outbox.OutboxWriter;
import com.checkout.shipping.domain.Address;
import com.checkout.shipping.domain.Item;
import com.checkout.shipping.domain.Shipment;
import com.checkout.shipping.domain.ShipmentRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.databind.SerializationFeature;
import com.fasterxml.jackson.databind.json.JsonMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;

import java.time.Clock;
import java.time.Instant;
import java.time.LocalDate;
import java.time.ZoneOffset;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ShippingCommandHandlerTest {

    private static final Clock CLOCK = Clock.fixed(Instant.parse("2026-09-23T14:05:12Z"), ZoneOffset.UTC);
    private static final Address ADDRESS =
            new Address("Av. Paulista", "1000", null, "São Paulo", "SP", "01310-100", "BR");

    private final ObjectMapper mapper = JsonMapper.builder().findAndAddModules()
            .disable(SerializationFeature.WRITE_DATES_AS_TIMESTAMPS).build();
    private final MessageFactory messages = new MessageFactory(mapper, "saga-orchestrator", CLOCK);
    private ShipmentRepository repo;
    private IdempotencyGuard idempotency;
    private OutboxWriter outbox;
    private ShippingCommandHandler handler;
    private final UUID orderId = UUID.randomUUID();

    @BeforeEach
    void setUp() {
        repo = mock(ShipmentRepository.class);
        idempotency = mock(IdempotencyGuard.class);
        outbox = mock(OutboxWriter.class);
        when(idempotency.tryMarkProcessed(any())).thenReturn(true);
        handler = new ShippingCommandHandler(repo, idempotency, outbox, messages, CLOCK);
    }

    private MessageEnvelope createCmd(String simulateShipping) {
        return messages.create(Topics.Types.SHIPMENT_CREATE, UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                new ShippingMessages.CreateCommand(ADDRESS, List.of(new Item("SKU-BOOK-001", 2)),
                        simulateShipping == null ? null : new Simulate(null, null, simulateShipping)));
    }

    private MessageEnvelope cancelCmd() {
        return messages.create(Topics.Types.SHIPMENT_CANCEL, UUID.randomUUID(), orderId, UUID.randomUUID(), null,
                new ShippingMessages.CancelCommand("STEP_TIMEOUT"));
    }

    private Shipment created(UUID shipmentId) {
        return new Shipment(orderId, shipmentId, Shipment.CREATED, "BR123456789", "LOCAL-EXPRESS",
                LocalDate.parse("2026-09-30"), ADDRESS, List.of(), false, null, null, 1);
    }

    private MessageEnvelope published() {
        ArgumentCaptor<MessageEnvelope> captor = ArgumentCaptor.forClass(MessageEnvelope.class);
        verify(outbox).publish(eq(Topics.SHIPPING_EVENTS), captor.capture());
        return captor.getValue();
    }

    @Test
    void criaEnvioEPublicaCreated() {
        MessageEnvelope cmd = createCmd(null);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(cmd);

        verify(repo).insert(any());
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.SHIPMENT_CREATED);
        assertThat(reply.causationId()).isEqualTo(cmd.messageId());
        assertThat(reply.payload().get("trackingCode").asText()).matches("BR\\d{9}");
        assertThat(reply.payload().get("carrier").asText()).isEqualTo("LOCAL-EXPRESS");
        assertThat(reply.payload().get("estimatedDeliveryDate").asText()).isEqualTo("2026-09-30");
    }

    @Test
    void createDuplicadoRepublicaMesmoEnvio() {
        UUID shipmentId = UUID.randomUUID();
        MessageEnvelope cmd = createCmd(null);
        when(idempotency.tryMarkProcessed(cmd.messageId())).thenReturn(false);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(created(shipmentId)));
        when(repo.incrementAttempts(orderId)).thenReturn(2);

        handler.handle(cmd);

        verify(repo, never()).insert(any());
        MessageEnvelope reply = published();
        assertThat(reply.payload().get("shipmentId").asText()).isEqualTo(shipmentId.toString());
        assertThat(reply.payload().get("trackingCode").asText()).isEqualTo("BR123456789");
    }

    @Test
    void simulateFailPublicaFailedCarrierRejected() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(createCmd("FAIL"));

        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.SHIPMENT_FAILED);
        assertThat(reply.payload().get("reason").asText()).isEqualTo("CARRIER_REJECTED");
    }

    @Test
    void timeoutCriaEnvioENaoResponde() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        when(repo.incrementAttempts(orderId)).thenReturn(1);

        handler.handle(createCmd("TIMEOUT"));

        verify(repo).insert(any());
        verify(outbox, never()).publish(anyString(), any());
    }

    @Test
    void timeoutOnceRespondeNoRetry() {
        MessageEnvelope cmd = createCmd("TIMEOUT_ONCE");
        when(idempotency.tryMarkProcessed(cmd.messageId())).thenReturn(false);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(created(UUID.randomUUID())));
        when(repo.incrementAttempts(orderId)).thenReturn(2);

        handler.handle(cmd);

        assertThat(published().type()).isEqualTo(Topics.Types.SHIPMENT_CREATED);
    }

    @Test
    void cancelDeEnvioCriadoCancela() {
        UUID shipmentId = UUID.randomUUID();
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(created(shipmentId)));

        handler.handle(cancelCmd());

        verify(repo).markCanceled(orderId);
        MessageEnvelope reply = published();
        assertThat(reply.type()).isEqualTo(Topics.Types.SHIPMENT_CANCELED);
        assertThat(reply.payload().get("shipmentId").asText()).isEqualTo(shipmentId.toString());
        assertThat(reply.payload().get("noop").asBoolean()).isFalse();
    }

    @Test
    void cancelSemEnvioGravaTombstoneECreateTardioFalha() {
        when(repo.findForUpdate(orderId)).thenReturn(Optional.empty());
        handler.handle(cancelCmd());

        ArgumentCaptor<Shipment> saved = ArgumentCaptor.forClass(Shipment.class);
        verify(repo).insert(saved.capture());
        assertThat(saved.getValue().status()).isEqualTo(Shipment.CANCELED);
        assertThat(saved.getValue().noop()).isTrue();
        assertThat(published().payload().get("noop").asBoolean()).isTrue();

        outbox = mock(OutboxWriter.class);
        handler = new ShippingCommandHandler(repo, idempotency, outbox, messages, CLOCK);
        when(repo.findForUpdate(orderId)).thenReturn(Optional.of(saved.getValue()));
        handler.handle(createCmd("TIMEOUT"));

        MessageEnvelope failed = published();
        assertThat(failed.type()).isEqualTo(Topics.Types.SHIPMENT_FAILED);
        assertThat(failed.payload().get("reason").asText()).isEqualTo("ALREADY_COMPENSATED");
    }
}
