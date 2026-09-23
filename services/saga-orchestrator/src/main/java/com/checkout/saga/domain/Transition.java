package com.checkout.saga.domain;

import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;

/** Efeitos de uma transição, aplicados pelo serviço numa única transação (outbox + log) e métricas pós-commit. */
public final class Transition {

    public record Command(String topic, String type, UUID messageId, UUID causationId, Object payload) {}

    public record StepEvent(Step step, String stepStatus, int attempt, SagaStatus sagaStatus, String detail) {}

    public record LogEntry(Step step, String action, String messageType, UUID messageId, int attempt, String detail) {}

    public sealed interface Metric {
        record Started() implements Metric {}
        record Completed(String outcome) implements Metric {}
        record Compensation(Step step) implements Metric {}
        record Timeout(Step step) implements Metric {}
        record Retry(Step step) implements Metric {}
        record StepDuration(Step step, String result, Duration duration) implements Metric {}
        record CompensationStuck(Step step) implements Metric {}
        record Resumed() implements Metric {}
    }

    public static final String COMMAND_SENT = "COMMAND_SENT";
    public static final String REPLY_RECEIVED = "REPLY_RECEIVED";
    public static final String TIMEOUT = "TIMEOUT";
    public static final String RETRY = "RETRY";
    public static final String COMPENSATION_STARTED = "COMPENSATION_STARTED";
    public static final String IGNORED_LATE_REPLY = "IGNORED_LATE_REPLY";
    public static final String COMPENSATION_STUCK = "COMPENSATION_STUCK";
    public static final String RESUMED_AFTER_RESTART = "RESUMED_AFTER_RESTART";

    public final List<Command> commands = new ArrayList<>();
    public final List<StepEvent> stepEvents = new ArrayList<>();
    public final List<LogEntry> logs = new ArrayList<>();
    public final List<Metric> metrics = new ArrayList<>();
    /** true se saga_instance mudou e precisa ser persistida. */
    public boolean stateChanged;
    /** true se a resposta foi aceita (causationId e type esperados). */
    public boolean accepted;

    public boolean hasLog(String action) {
        return logs.stream().anyMatch(l -> l.action().equals(action));
    }
}
