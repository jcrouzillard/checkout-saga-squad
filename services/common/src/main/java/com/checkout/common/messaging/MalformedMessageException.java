package com.checkout.common.messaging;

/** Mensagem venenosa (JSON/envelope inválido). O error handler envia para {@code <tópico>.DLT} após 3 tentativas. */
public class MalformedMessageException extends RuntimeException {
    public MalformedMessageException(String message) {
        super(message);
    }

    public MalformedMessageException(String message, Throwable cause) {
        super(message, cause);
    }
}
