package com.checkout.payment.domain;

import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.util.Optional;
import java.util.UUID;

/** Acesso JDBC à tabela {@code payments}. Métodos de escrita exigem transação do chamador. */
@Repository
public class PaymentRepository {

    private static final RowMapper<Payment> MAPPER = (rs, n) -> new Payment(
            rs.getObject("order_id", UUID.class),
            rs.getObject("payment_id", UUID.class),
            rs.getString("status"),
            rs.getString("customer_id"),
            rs.getBigDecimal("amount"),
            rs.getString("currency"),
            rs.getString("authorization_code"),
            rs.getBoolean("noop"),
            rs.getInt("attempts"));

    private final JdbcClient jdbc;

    public PaymentRepository(JdbcClient jdbc) {
        this.jdbc = jdbc;
    }

    public Optional<Payment> find(UUID orderId) {
        return jdbc.sql("SELECT * FROM payments WHERE order_id = :id").param("id", orderId).query(MAPPER).optional();
    }

    public Optional<Payment> findForUpdate(UUID orderId) {
        return jdbc.sql("SELECT * FROM payments WHERE order_id = :id FOR UPDATE").param("id", orderId)
                .query(MAPPER).optional();
    }

    public void insert(Payment p) {
        jdbc.sql("""
                INSERT INTO payments (order_id, payment_id, status, customer_id, amount, currency, authorization_code,
                                      noop, attempts, created_at, updated_at)
                VALUES (:orderId, :paymentId, :status, :customerId, :amount, :currency, :authorizationCode,
                        :noop, :attempts, now(), now())
                """)
                .param("orderId", p.orderId())
                .param("paymentId", p.paymentId())
                .param("status", p.status())
                .param("customerId", p.customerId())
                .param("amount", p.amount())
                .param("currency", p.currency())
                .param("authorizationCode", p.authorizationCode())
                .param("noop", p.noop())
                .param("attempts", p.attempts())
                .update();
    }

    public void markRefunded(UUID orderId) {
        jdbc.sql("UPDATE payments SET status = 'REFUNDED', noop = FALSE, updated_at = now() WHERE order_id = :id")
                .param("id", orderId).update();
    }

    /** Incrementa e devolve o nº de comandos {@code payment.authorize} recebidos para o pedido. */
    public int incrementAttempts(UUID orderId) {
        return jdbc.sql("UPDATE payments SET attempts = attempts + 1, updated_at = now() WHERE order_id = :id RETURNING attempts")
                .param("id", orderId).query(Integer.class).single();
    }
}
