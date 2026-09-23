package com.checkout.saga.app;

import com.checkout.saga.domain.SagaSettings;
import com.checkout.saga.domain.SagaStateMachine;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.time.Clock;

@Configuration(proxyBeanMethods = false)
public class SagaConfiguration {

    @Bean
    public SagaStateMachine sagaStateMachine(SagaSettings settings, Clock clock) {
        return new SagaStateMachine(settings, clock);
    }
}
