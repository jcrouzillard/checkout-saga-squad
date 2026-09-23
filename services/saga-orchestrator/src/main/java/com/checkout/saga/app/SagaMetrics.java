package com.checkout.saga.app;

import com.checkout.saga.domain.Step;
import com.checkout.saga.domain.Transition.Metric;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import org.springframework.stereotype.Component;

import java.util.List;
import java.util.concurrent.atomic.AtomicLong;

/**
 * Métricas de negócio exatamente como docs/observability.md §1. {@code saga.in.flight} é derivado do banco
 * (count de sagas não terminais, atualizado pelo scheduler) → não zera após reinício.
 */
@Component
public class SagaMetrics {

    private static final List<String> OUTCOMES = List.of("CONFIRMED", "CANCELED");
    private static final List<Step> STEPS = List.of(Step.INVENTORY, Step.PAYMENT, Step.SHIPPING);

    private final MeterRegistry registry;
    private final AtomicLong inFlight = new AtomicLong();

    public SagaMetrics(MeterRegistry registry) {
        this.registry = registry;
        // Pré-registra as séries para que o dashboard mostre 0 em vez de "No data".
        Counter.builder("saga.started").register(registry);
        OUTCOMES.forEach(o -> Counter.builder("saga.completed").tag("outcome", o).register(registry));
        STEPS.forEach(s -> {
            Counter.builder("saga.compensations").tag("step", s.name()).register(registry);
            Counter.builder("saga.timeouts").tag("step", s.name()).register(registry);
            Counter.builder("saga.retries").tag("step", s.name()).register(registry);
        });
        Counter.builder("saga.resumed").register(registry);
        Gauge.builder("saga.in.flight", inFlight, AtomicLong::get).register(registry);
    }

    public void setInFlight(long value) {
        inFlight.set(value);
    }

    public void record(Metric m) {
        switch (m) {
            case Metric.Started s -> registry.counter("saga.started").increment();
            case Metric.Completed c -> registry.counter("saga.completed", "outcome", c.outcome()).increment();
            case Metric.Compensation c -> registry.counter("saga.compensations", "step", c.step().name()).increment();
            case Metric.Timeout t -> registry.counter("saga.timeouts", "step", t.step().name()).increment();
            case Metric.Retry r -> registry.counter("saga.retries", "step", r.step().name()).increment();
            case Metric.StepDuration d -> {
                if (d.step().isParticipant()) {
                    Timer.builder("saga.step.duration").tag("step", d.step().name()).tag("result", d.result())
                            .register(registry).record(d.duration());
                }
            }
            case Metric.Resumed r -> registry.counter("saga.resumed").increment();
            case Metric.CompensationStuck c ->
                    registry.counter("saga.compensation.stuck", "step", c.step().name()).increment();
        }
    }
}
