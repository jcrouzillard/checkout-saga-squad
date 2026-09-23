package com.checkout.saga.app;

import com.checkout.saga.domain.OrderSnapshot;
import com.checkout.saga.domain.SagaInstance;
import com.checkout.saga.domain.SagaStatus;
import com.checkout.saga.domain.Step;
import com.checkout.saga.domain.Transition;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.dao.OptimisticLockingFailureException;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/** Persistência de saga_instance / saga_step_log (JdbcClient). */
@Repository
public class SagaRepository {

    public record Due(UUID sagaId, String traceParent) {}

    public record LogRow(Step step, String action, String messageType, UUID messageId, Integer attempt, String detail,
                         Instant at) {}

    private static final String COLUMNS = """
            saga_id, order_id, status, current_step, delivery_type, order_snapshot::text AS order_snapshot, payment_id,
            shipment_id, tracking_code, last_command_id, last_command_type, last_causation_id, attempt, deadline_at,
            next_retry_at, step_started_at, failure_reason, failed_step, failure_message, correlation_id, trace_parent,
            version, created_at, updated_at""";
    private static final String NOT_TERMINAL = "status NOT IN ('COMPLETED','CANCELED')";

    private final JdbcClient jdbc;
    private final ObjectMapper mapper;

    public SagaRepository(JdbcClient jdbc, ObjectMapper mapper) {
        this.jdbc = jdbc;
        this.mapper = mapper;
    }

    public boolean existsByOrderId(UUID orderId) {
        return jdbc.sql("SELECT count(*) FROM saga_instance WHERE order_id = :id").param("id", orderId)
                .query(Long.class).single() > 0;
    }

    public Optional<SagaInstance> findById(UUID sagaId) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM saga_instance WHERE saga_id = :id").param("id", sagaId)
                .query(this::map).optional();
    }

    public Optional<SagaInstance> findByOrderId(UUID orderId) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM saga_instance WHERE order_id = :id").param("id", orderId)
                .query(this::map).optional();
    }

    /** Lock pessimista para processar uma resposta (bloqueia até o scheduler liberar a linha). */
    public Optional<SagaInstance> lockById(UUID sagaId) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM saga_instance WHERE saga_id = :id FOR UPDATE")
                .param("id", sagaId).query(this::map).optional();
    }

    /** Candidatas do scheduler: deadline ou retry vencidos (sem lock; o lock é por saga, com SKIP LOCKED). */
    public List<Due> findDue(Instant now, int limit) {
        return jdbc.sql("SELECT saga_id, trace_parent FROM saga_instance WHERE " + NOT_TERMINAL
                        + " AND (deadline_at <= :now OR next_retry_at <= :now) ORDER BY updated_at LIMIT :limit")
                .param("now", Timestamp.from(now)).param("limit", limit)
                .query((rs, n) -> new Due(rs.getObject("saga_id", UUID.class), rs.getString("trace_parent")))
                .list();
    }

    /** {@code SELECT ... FOR UPDATE SKIP LOCKED} de uma saga ainda vencida (outra instância pode tê-la pego). */
    public Optional<SagaInstance> lockDue(UUID sagaId, Instant now) {
        return jdbc.sql("SELECT " + COLUMNS + " FROM saga_instance WHERE saga_id = :id AND " + NOT_TERMINAL
                        + " AND (deadline_at <= :now OR next_retry_at <= :now) FOR UPDATE SKIP LOCKED")
                .param("id", sagaId).param("now", Timestamp.from(now)).query(this::map).optional();
    }

    public long countInFlight() {
        return jdbc.sql("SELECT count(*) FROM saga_instance WHERE " + NOT_TERMINAL).query(Long.class).single();
    }

    public List<UUID> inFlightIds(int limit) {
        return jdbc.sql("SELECT saga_id FROM saga_instance WHERE " + NOT_TERMINAL + " ORDER BY created_at LIMIT :l")
                .param("l", limit).query(UUID.class).list();
    }

    public void insert(SagaInstance s) {
        jdbc.sql("""
                INSERT INTO saga_instance (saga_id, order_id, status, current_step, delivery_type, order_snapshot,
                  payment_id, shipment_id, tracking_code, last_command_id, last_command_type, last_causation_id,
                  attempt, deadline_at, next_retry_at, step_started_at, failure_reason, failed_step, failure_message,
                  correlation_id, trace_parent, version, created_at, updated_at)
                VALUES (:sagaId, :orderId, :status, :currentStep, :deliveryType, CAST(:snapshot AS jsonb), :paymentId,
                  :shipmentId, :trackingCode, :lastCommandId, :lastCommandType, :lastCausationId, :attempt,
                  :deadlineAt, :nextRetryAt, :stepStartedAt, :failureReason, :failedStep, :failureMessage,
                  :correlationId, :traceParent, 0, :createdAt, :updatedAt)
                """)
                .param("sagaId", s.sagaId).param("orderId", s.orderId).param("deliveryType", s.deliveryType)
                .param("snapshot", toJson(s.snapshot)).param("correlationId", s.correlationId)
                .param("traceParent", s.traceParent).param("createdAt", ts(s.createdAt))
                .params(mutableParams(s))
                .update();
    }

    public void update(SagaInstance s) {
        int n = jdbc.sql("""
                UPDATE saga_instance SET status = :status, current_step = :currentStep, payment_id = :paymentId,
                  shipment_id = :shipmentId, tracking_code = :trackingCode, last_command_id = :lastCommandId,
                  last_command_type = :lastCommandType, last_causation_id = :lastCausationId, attempt = :attempt,
                  deadline_at = :deadlineAt, next_retry_at = :nextRetryAt, step_started_at = :stepStartedAt,
                  failure_reason = :failureReason, failed_step = :failedStep, failure_message = :failureMessage,
                  updated_at = :updatedAt, version = version + 1
                WHERE saga_id = :sagaId AND version = :version
                """)
                .param("sagaId", s.sagaId).param("version", s.version)
                .params(mutableParams(s))
                .update();
        if (n != 1) {
            throw new OptimisticLockingFailureException("saga " + s.sagaId + " alterada concorrentemente");
        }
        s.version++;
    }

    public void insertLog(UUID sagaId, Transition.LogEntry l, Instant at) {
        jdbc.sql("""
                INSERT INTO saga_step_log (saga_id, step, action, message_type, message_id, attempt, detail, created_at)
                VALUES (:sagaId, :step, :action, :type, :messageId, :attempt, :detail, :at)
                """)
                .param("sagaId", sagaId).param("step", l.step() == null ? null : l.step().name())
                .param("action", l.action()).param("type", l.messageType()).param("messageId", l.messageId())
                .param("attempt", l.attempt()).param("detail", l.detail()).param("at", ts(at))
                .update();
    }

    public List<LogRow> logs(UUID sagaId) {
        return jdbc.sql("""
                SELECT step, action, message_type, message_id, attempt, detail, created_at FROM saga_step_log
                WHERE saga_id = :id ORDER BY id
                """)
                .param("id", sagaId)
                .query((rs, n) -> new LogRow(rs.getString("step") == null ? null : Step.valueOf(rs.getString("step")),
                        rs.getString("action"), rs.getString("message_type"), rs.getObject("message_id", UUID.class),
                        (Integer) rs.getObject("attempt"), rs.getString("detail"),
                        rs.getTimestamp("created_at").toInstant()))
                .list();
    }

    private java.util.Map<String, Object> mutableParams(SagaInstance s) {
        java.util.Map<String, Object> m = new java.util.HashMap<>();
        m.put("status", s.status.name());
        m.put("currentStep", s.currentStep == null ? null : s.currentStep.name());
        m.put("paymentId", s.paymentId);
        m.put("shipmentId", s.shipmentId);
        m.put("trackingCode", s.trackingCode);
        m.put("lastCommandId", s.lastCommandId);
        m.put("lastCommandType", s.lastCommandType);
        m.put("lastCausationId", s.lastCausationId);
        m.put("attempt", s.attempt);
        m.put("deadlineAt", ts(s.deadlineAt));
        m.put("nextRetryAt", ts(s.nextRetryAt));
        m.put("stepStartedAt", ts(s.stepStartedAt));
        m.put("failureReason", s.failureReason);
        m.put("failedStep", s.failedStep == null ? null : s.failedStep.name());
        m.put("failureMessage", s.failureMessage);
        m.put("updatedAt", ts(s.updatedAt));
        return m;
    }

    private SagaInstance map(ResultSet rs, int n) throws SQLException {
        SagaInstance s = new SagaInstance();
        s.sagaId = rs.getObject("saga_id", UUID.class);
        s.orderId = rs.getObject("order_id", UUID.class);
        s.status = SagaStatus.valueOf(rs.getString("status"));
        s.currentStep = rs.getString("current_step") == null ? null : Step.valueOf(rs.getString("current_step"));
        s.deliveryType = rs.getString("delivery_type");
        s.snapshot = fromJson(rs.getString("order_snapshot"));
        s.paymentId = rs.getObject("payment_id", UUID.class);
        s.shipmentId = rs.getObject("shipment_id", UUID.class);
        s.trackingCode = rs.getString("tracking_code");
        s.lastCommandId = rs.getObject("last_command_id", UUID.class);
        s.lastCommandType = rs.getString("last_command_type");
        s.lastCausationId = rs.getObject("last_causation_id", UUID.class);
        s.attempt = rs.getInt("attempt");
        s.deadlineAt = instant(rs, "deadline_at");
        s.nextRetryAt = instant(rs, "next_retry_at");
        s.stepStartedAt = instant(rs, "step_started_at");
        s.failureReason = rs.getString("failure_reason");
        s.failedStep = rs.getString("failed_step") == null ? null : Step.valueOf(rs.getString("failed_step"));
        s.failureMessage = rs.getString("failure_message");
        s.correlationId = rs.getObject("correlation_id", UUID.class);
        s.traceParent = rs.getString("trace_parent");
        s.version = rs.getLong("version");
        s.createdAt = instant(rs, "created_at");
        s.updatedAt = instant(rs, "updated_at");
        return s;
    }

    private static Instant instant(ResultSet rs, String col) throws SQLException {
        Timestamp t = rs.getTimestamp(col);
        return t == null ? null : t.toInstant();
    }

    private static Timestamp ts(Instant i) {
        return i == null ? null : Timestamp.from(i);
    }

    private String toJson(OrderSnapshot s) {
        try {
            return mapper.writeValueAsString(s);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException(e);
        }
    }

    private OrderSnapshot fromJson(String json) {
        try {
            return mapper.readValue(json, OrderSnapshot.class);
        } catch (JsonProcessingException e) {
            throw new IllegalStateException("order_snapshot inválido", e);
        }
    }
}
