package com.checkout.order.domain;

import com.checkout.order.messaging.OrderPayloads.Line;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

@Repository
public class OrderRepository {

    public record HistoryEntry(String step, String status, int attempt, String detail, Instant at) {}

    private static final String COLUMNS = """
            order_id, saga_id, idempotency_key, request_hash, customer_id, status, delivery_type, total_amount,
            currency, shipping_address::text AS shipping_address, payment_id, shipment_id, tracking_code,
            cancellation_reason, failed_step, cancellation_message, correlation_id, created_at, updated_at""";

    private final JdbcClient jdbc;

    public OrderRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<OrderRecord> findById(UUID orderId) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM orders WHERE order_id = :id").param("id", orderId)
                .query(OrderRepository::map).optional();
    }

    public Optional<OrderRecord> lockById(UUID orderId) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM orders WHERE order_id = :id FOR UPDATE").param("id", orderId)
                .query(OrderRepository::map).optional();
    }

    public Optional<OrderRecord> findByIdempotencyKey(String key) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM orders WHERE idempotency_key = :k").param("k", key)
                .query(OrderRepository::map).optional();
    }

    public boolean exists(UUID orderId) {
        return jdbc.sql("SELECT count(*) FROM orders WHERE order_id = :id").param("id", orderId)
                .query(Long.class).single() > 0;
    }

    public void insert(OrderRecord o, String simulateJson, List<Line> items) {
        jdbc.sql("""
                INSERT INTO orders (order_id, saga_id, idempotency_key, request_hash, customer_id, status, delivery_type,
                  total_amount, currency, shipping_address, simulate, correlation_id, created_at, updated_at)
                VALUES (:orderId, :sagaId, :key, :hash, :customerId, :status, :deliveryType, :total, :currency,
                  CAST(:address AS jsonb), CAST(:simulate AS jsonb), :correlationId, :createdAt, :updatedAt)
                """)
                .param("orderId", o.orderId()).param("sagaId", o.sagaId()).param("key", o.idempotencyKey())
                .param("hash", o.requestHash()).param("customerId", o.customerId()).param("status", o.status())
                .param("deliveryType", o.deliveryType()).param("total", o.totalAmount())
                .param("currency", o.currency()).param("address", o.shippingAddressJson())
                .param("simulate", simulateJson).param("correlationId", o.correlationId())
                .param("createdAt", Timestamp.from(o.createdAt())).param("updatedAt", Timestamp.from(o.updatedAt()))
                .update();
        int line = 1;
        for (Line item : items) {
            jdbc.sql("""
                    INSERT INTO order_items (order_id, line_no, sku, quantity, unit_price)
                    VALUES (:orderId, :line, :sku, :qty, :price)
                    """)
                    .param("orderId", o.orderId()).param("line", line++).param("sku", item.sku())
                    .param("qty", item.quantity()).param("price", item.unitPrice()).update();
        }
    }

    public List<Line> items(UUID orderId) {
        return jdbc.sql("SELECT sku, quantity, unit_price FROM order_items WHERE order_id = :id ORDER BY line_no")
                .param("id", orderId)
                .query((rs, n) -> new Line(rs.getString("sku"), rs.getInt("quantity"), rs.getBigDecimal("unit_price")))
                .list();
    }

    public void confirm(UUID orderId, UUID paymentId, UUID shipmentId, String trackingCode, Instant at) {
        jdbc.sql("""
                UPDATE orders SET status = 'CONFIRMED', payment_id = :paymentId, shipment_id = :shipmentId,
                  tracking_code = :tracking, updated_at = :at WHERE order_id = :id
                """)
                .param("paymentId", paymentId).param("shipmentId", shipmentId).param("tracking", trackingCode)
                .param("at", Timestamp.from(at)).param("id", orderId).update();
    }

    public void cancel(UUID orderId, String reason, String failedStep, String message, Instant at) {
        jdbc.sql("""
                UPDATE orders SET status = 'CANCELED', cancellation_reason = :reason, failed_step = :failedStep,
                  cancellation_message = :message, updated_at = :at WHERE order_id = :id
                """)
                .param("reason", reason).param("failedStep", failedStep).param("message", message)
                .param("at", Timestamp.from(at)).param("id", orderId).update();
    }

    public void addHistory(UUID orderId, String step, String status, int attempt, String detail, Instant at) {
        jdbc.sql("""
                INSERT INTO order_status_history (order_id, step, status, attempt, detail, at)
                VALUES (:id, :step, :status, :attempt, :detail, :at)
                """)
                .param("id", orderId).param("step", step).param("status", status).param("attempt", attempt)
                .param("detail", detail).param("at", Timestamp.from(at)).update();
    }

    public List<HistoryEntry> history(UUID orderId) {
        return jdbc.sql("""
                SELECT step, status, attempt, detail, at FROM order_status_history
                WHERE order_id = :id ORDER BY at, id
                """)
                .param("id", orderId)
                .query((rs, n) -> new HistoryEntry(rs.getString("step"), rs.getString("status"), rs.getInt("attempt"),
                        rs.getString("detail"), rs.getTimestamp("at").toInstant()))
                .list();
    }

    private static OrderRecord map(ResultSet rs, int n) throws SQLException {
        return new OrderRecord(rs.getObject("order_id", UUID.class), rs.getObject("saga_id", UUID.class),
                rs.getString("idempotency_key"), rs.getString("request_hash"), rs.getString("customer_id"),
                rs.getString("status"), rs.getString("delivery_type"), rs.getBigDecimal("total_amount"),
                rs.getString("currency"), rs.getString("shipping_address"), rs.getObject("payment_id", UUID.class),
                rs.getObject("shipment_id", UUID.class), rs.getString("tracking_code"),
                rs.getString("cancellation_reason"), rs.getString("failed_step"), rs.getString("cancellation_message"),
                rs.getObject("correlation_id", UUID.class), rs.getTimestamp("created_at").toInstant(),
                rs.getTimestamp("updated_at").toInstant());
    }
}
