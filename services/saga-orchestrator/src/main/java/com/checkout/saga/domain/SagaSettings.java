package com.checkout.saga.domain;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Parâmetros de timeout/retry (api.md §5). */
@ConfigurationProperties("saga")
public record SagaSettings(
        @DefaultValue("5000") long stepTimeoutMs,
        @DefaultValue("2") int stepMaxRetries,
        @DefaultValue("1000") long retryBackoffMs,
        @DefaultValue("30000") long compensationBackoffMaxMs,
        @DefaultValue("5") int compensationAlertAfter,
        @DefaultValue("1000") long timeoutScanIntervalMs) {

    public static SagaSettings defaults() {
        return new SagaSettings(5000, 2, 1000, 30000, 5, 1000);
    }
}
