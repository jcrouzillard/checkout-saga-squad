package com.checkout.shipping.domain;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.sql.Date;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** Acesso JDBC à tabela {@code shipments}. Métodos de escrita exigem transação do chamador. */
@Repository
public class ShipmentRepository {

    private static final TypeReference<List<Item>> ITEMS = new TypeReference<>() {};

    private final JdbcClient jdbc;
    private final ObjectMapper mapper;

    public ShipmentRepository(JdbcClient jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public Optional<Shipment> find(UUID orderId) {
        return jdbc.sql("SELECT * FROM shipments WHERE order_id = :id").param("id", orderId).query(mapper()).optional();
    }

    public Optional<Shipment> findForUpdate(UUID orderId) {
        return jdbc.sql("SELECT * FROM shipments WHERE order_id = :id FOR UPDATE").param("id", orderId)
                .query(mapper()).optional();
    }

    public void insert(Shipment s) {
        jdbc.sql("""
                INSERT INTO shipments (order_id, shipment_id, status, tracking_code, carrier, estimated_delivery_date,
                                       address, items, noop, reason, message, attempts, created_at, updated_at)
                VALUES (:orderId, :shipmentId, :status, :trackingCode, :carrier, :eta, CAST(:address AS jsonb),
                        CAST(:items AS jsonb), :noop, :reason, :message, :attempts, now(), now())
                """)
                .param("orderId", s.orderId())
                .param("shipmentId", s.shipmentId())
                .param("status", s.status())
                .param("trackingCode", s.trackingCode())
                .param("carrier", s.carrier())
                .param("eta", s.estimatedDeliveryDate() == null ? null : Date.valueOf(s.estimatedDeliveryDate()))
                .param("address", s.address() == null ? null : json(s.address()))
                .param("items", json(s.items() == null ? List.of() : s.items()))
                .param("noop", s.noop())
                .param("reason", s.reason())
                .param("message", s.message())
                .param("attempts", s.attempts())
                .update();
    }

    public void markCanceled(UUID orderId) {
        jdbc.sql("UPDATE shipments SET status = 'CANCELED', noop = FALSE, updated_at = now() WHERE order_id = :id")
                .param("id", orderId).update();
    }

    /** Incrementa e devolve o nº de comandos {@code shipment.create} recebidos para o pedido. */
    public int incrementAttempts(UUID orderId) {
        return jdbc.sql("UPDATE shipments SET attempts = attempts + 1, updated_at = now() WHERE order_id = :id RETURNING attempts")
                .param("id", orderId).query(Integer.class).single();
    }

    private RowMapper<Shipment> mapper() {
        return (rs, n) -> {
            Date eta = rs.getDate("estimated_delivery_date");
            String address = rs.getString("address");
            return new Shipment(
                    rs.getObject("order_id", UUID.class),
                    rs.getObject("shipment_id", UUID.class),
                    rs.getString("status"),
                    rs.getString("tracking_code"),
                    rs.getString("carrier"),
                    eta == null ? null : eta.toLocalDate(),
                    address == null ? null : read(address, new TypeReference<Address>() {}),
                    read(rs.getString("items"), ITEMS),
                    rs.getBoolean("noop"),
                    rs.getString("reason"),
                    rs.getString("message"),
                    rs.getInt("attempts"));
        };
    }

    private String json(Object value) {
        try {
            return mapper.writeValueAsString(value);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private <T> T read(String json, TypeReference<T> type) {
        try {
            return mapper.readValue(json, type);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }
}
