package com.checkout.inventory.domain;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class ReplyPolicyTest {

    @Test
    void semSimulacaoSempreResponde() {
        assertThat(ReplyPolicy.shouldReply(null, 1)).isTrue();
        assertThat(ReplyPolicy.shouldReply("OUT_OF_STOCK", 1)).isTrue();
    }

    @Test
    void timeoutNuncaResponde() {
        assertThat(ReplyPolicy.shouldReply("TIMEOUT", 1)).isFalse();
        assertThat(ReplyPolicy.shouldReply("TIMEOUT", 3)).isFalse();
    }

    @Test
    void timeoutOnceRespondeAPartirDaSegundaTentativa() {
        assertThat(ReplyPolicy.shouldReply("TIMEOUT_ONCE", 1)).isFalse();
        assertThat(ReplyPolicy.shouldReply("TIMEOUT_ONCE", 2)).isTrue();
    }
}
