package com.checkout.inventory.domain;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/** Acesso JDBC às tabelas {@code stock} e {@code reservations}. Todos os métodos exigem transação do chamador. */
@Repository
public class InventoryRepository {

    private static final TypeReference<List<Item>> ITEMS = new TypeReference<>() {};
    private static final TypeReference<List<RejectionDetail>> DETAILS = new TypeReference<>() {};

    private final JdbcClient jdbc;
    private final ObjectMapper mapper;

    public InventoryRepository(JdbcClient jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    // ---------------------------------------------------------------- stock

    public Optional<StockLevel> findStock(String sku) {
        return jdbc.sql("SELECT sku, available, reserved FROM stock WHERE sku = :sku")
                .param("sku", sku)
                .query((rs, n) -> new StockLevel(rs.getString("sku"), rs.getInt("available"), rs.getInt("reserved")))
                .optional();
    }

    /** Saldo disponível sem lock (usado só para montar detalhes de rejeição simulada). */
    public Map<String, Integer> availableOf(Collection<String> skus) {
        return queryAvailable("SELECT sku, available FROM stock WHERE sku IN (:skus) ORDER BY sku", skus);
    }

    /**
     * Trava ({@code FOR UPDATE}) as linhas dos SKUs em ordem de SKU — ordem determinística evita deadlock entre
     * reservas concorrentes — e devolve o saldo disponível. SKU inexistente fica fora do mapa.
     */
    public Map<String, Integer> lockAvailable(Collection<String> skus) {
        return queryAvailable("SELECT sku, available FROM stock WHERE sku IN (:skus) ORDER BY sku FOR UPDATE", skus);
    }

    private Map<String, Integer> queryAvailable(String sql, Collection<String> skus) {
        Map<String, Integer> result = new LinkedHashMap<>();
        if (skus.isEmpty()) {
            return result;
        }
        jdbc.sql(sql).param("skus", skus).query(rs -> {
            result.put(rs.getString("sku"), rs.getInt("available"));
        });
        return result;
    }

    /** Débito condicional atômico; {@code false} se o saldo não for suficiente. */
    public boolean reserveStock(String sku, int quantity) {
        return jdbc.sql("""
                UPDATE stock SET available = available - :q, reserved = reserved + :q,
                                 version = version + 1, updated_at = now()
                WHERE sku = :sku AND available >= :q
                """)
                .param("q", quantity).param("sku", sku).update() == 1;
    }

    /** Devolve ao disponível o que estava reservado. */
    public void releaseStock(String sku, int quantity) {
        int updated = jdbc.sql("""
                UPDATE stock SET available = available + :q, reserved = GREATEST(reserved - :q, 0),
                                 version = version + 1, updated_at = now()
                WHERE sku = :sku
                """)
                .param("q", quantity).param("sku", sku).update();
        if (updated != 1) {
            throw new IllegalStateException("SKU " + sku + " não encontrado ao liberar reserva");
        }
    }

    // ---------------------------------------------------------------- reservations

    public Optional<Reservation> findReservation(UUID orderId) {
        return jdbc.sql("SELECT * FROM reservations WHERE order_id = :id").param("id", orderId)
                .query(reservationMapper()).optional();
    }

    /** Lê a reserva travando a linha (serializa comandos concorrentes do mesmo pedido). */
    public Optional<Reservation> findReservationForUpdate(UUID orderId) {
        return jdbc.sql("SELECT * FROM reservations WHERE order_id = :id FOR UPDATE").param("id", orderId)
                .query(reservationMapper()).optional();
    }

    public void insertReservation(Reservation r) {
        jdbc.sql("""
                INSERT INTO reservations (order_id, reservation_id, status, items, noop, reason, message, details,
                                          attempts, created_at, updated_at)
                VALUES (:orderId, :reservationId, :status, CAST(:items AS jsonb), :noop, :reason, :message,
                        CAST(:details AS jsonb), :attempts, now(), now())
                """)
                .param("orderId", r.orderId())
                .param("reservationId", r.reservationId())
                .param("status", r.status())
                .param("items", json(r.items() == null ? List.of() : r.items()))
                .param("noop", r.noop())
                .param("reason", r.reason())
                .param("message", r.message())
                .param("details", r.details() == null ? null : json(r.details()))
                .param("attempts", r.attempts())
                .update();
    }

    public void markReleased(UUID orderId) {
        jdbc.sql("UPDATE reservations SET status = 'RELEASED', noop = FALSE, updated_at = now() WHERE order_id = :id")
                .param("id", orderId).update();
    }

    /** Incrementa e devolve o nº de comandos {@code inventory.reserve} recebidos para o pedido. */
    public int incrementAttempts(UUID orderId) {
        return jdbc.sql("""
                UPDATE reservations SET attempts = attempts + 1, updated_at = now() WHERE order_id = :id
                RETURNING attempts
                """)
                .param("id", orderId).query(Integer.class).single();
    }

    private RowMapper<Reservation> reservationMapper() {
        return (rs, n) -> new Reservation(
                rs.getObject("order_id", UUID.class),
                rs.getObject("reservation_id", UUID.class),
                rs.getString("status"),
                read(rs.getString("items"), ITEMS),
                rs.getBoolean("noop"),
                rs.getString("reason"),
                rs.getString("message"),
                rs.getString("details") == null ? null : read(rs.getString("details"), DETAILS),
                rs.getInt("attempts"));
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
