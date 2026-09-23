package com.checkout.common.observability;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanContext;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.Scope;
import io.opentelemetry.context.propagation.TextMapGetter;

import java.util.Collections;
import java.util.function.Supplier;

/**
 * Captura/restaura o contexto W3C {@code traceparent}. Sem o agente OTel a API é no-op
 * ({@link #currentTraceparent()} devolve null e {@link #callWith} só executa).
 */
public final class TraceContext {
    private TraceContext() {}

    private static final TextMapGetter<String> GETTER = new TextMapGetter<>() {
        @Override
        public Iterable<String> keys(String carrier) {
            return Collections.singletonList("traceparent");
        }

        @Override
        public String get(String carrier, String key) {
            return "traceparent".equals(key) ? carrier : null;
        }
    };

    /** traceparent do span corrente ({@code 00-<traceId>-<spanId>-<flags>}) ou null. */
    public static String currentTraceparent() {
        SpanContext sc = Span.current().getSpanContext();
        if (!sc.isValid()) {
            return null;
        }
        return "00-" + sc.getTraceId() + "-" + sc.getSpanId() + "-" + sc.getTraceFlags().asHex();
    }

    /** Executa {@code action} com o contexto restaurado a partir de {@code traceparent} (se houver). */
    public static <T> T callWith(String traceparent, Supplier<T> action) {
        if (traceparent == null || traceparent.isBlank()) {
            return action.get();
        }
        Context ctx = W3CTraceContextPropagator.getInstance().extract(Context.root(), traceparent, GETTER);
        try (Scope ignored = ctx.makeCurrent()) {
            return action.get();
        }
    }

    public static void runWith(String traceparent, Runnable action) {
        callWith(traceparent, () -> {
            action.run();
            return null;
        });
    }
}
