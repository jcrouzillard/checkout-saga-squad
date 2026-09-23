package com.checkout.payment.domain;

import com.checkout.common.messaging.Simulate;

/**
 * Decide se a resposta de um comando de AÇÃO deve ser publicada (events.md §3 e §5.2).
 * {@code attempts} = nº de vezes que o comando de ação foi recebido para o pedido (persistido), incluindo esta.
 */
public final class ReplyPolicy {
    private ReplyPolicy() {}

    public static boolean shouldReply(String simulateMode, int attempts) {
        if (Simulate.TIMEOUT.equals(simulateMode)) {
            return false;                 // executa a ação e nunca responde (nem nos retries)
        }
        if (Simulate.TIMEOUT_ONCE.equals(simulateMode)) {
            return attempts >= 2;         // silêncio na 1ª tentativa; responde a partir do retry
        }
        return true;
    }
}
