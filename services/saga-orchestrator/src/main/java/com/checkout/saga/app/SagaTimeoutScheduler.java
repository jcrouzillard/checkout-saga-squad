package com.checkout.saga.app;

import com.checkout.common.observability.TraceContext;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.context.event.ApplicationReadyEvent;
import org.springframework.context.event.EventListener;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.Clock;
import java.time.Instant;
import java.util.List;

/**
 * Varre deadlines/retries vencidos (saga.md §3.2). Estado 100% no banco: após um reinício o primeiro ciclo já
 * encontra os prazos que venceram durante a queda (retomada §3.5). Restaura o traceparent da saga (§3.6).
 */
@Component
public class SagaTimeoutScheduler {

    private static final Logger log = LoggerFactory.getLogger(SagaTimeoutScheduler.class);
    private static final int BATCH = 50;

    private final SagaRepository repo;
    private final SagaService service;
    private final SagaMetrics metrics;
    private final Clock clock;

    public SagaTimeoutScheduler(SagaRepository repo, SagaService service, SagaMetrics metrics, Clock clock) {
        this.repo = repo;
        this.service = service;
        this.metrics = metrics;
        this.clock = clock;
    }

    @EventListener(ApplicationReadyEvent.class)
    public void logRecovery() {
        try {
            long n = repo.countInFlight();
            metrics.setInFlight(n);
            List<java.util.UUID> ids = repo.inFlightIds(100);
            log.info("Recuperação de sagas em andamento: {} saga(s) não terminais retomadas do banco {}", n, ids);
        } catch (Exception e) {
            log.warn("Não foi possível listar sagas em andamento no startup: {}", e.toString());
        }
    }

    @Scheduled(fixedDelayString = "${saga.timeout-scan-interval-ms:1000}")
    public void scan() {
        try {
            List<SagaRepository.Due> due = repo.findDue(Instant.now(clock), BATCH);
            for (SagaRepository.Due d : due) {
                try {
                    TraceContext.runWith(d.traceParent(), () -> service.tick(d.sagaId()));
                } catch (Exception e) {
                    log.warn("Falha ao processar timeout da saga {}: {}", d.sagaId(), e.toString());
                }
            }
            metrics.setInFlight(repo.countInFlight());
        } catch (Exception e) {
            log.warn("Scheduler de timeouts falhou; nova tentativa no próximo ciclo: {}", e.toString());
        }
    }
}
