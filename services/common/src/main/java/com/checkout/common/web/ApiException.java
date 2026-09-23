package com.checkout.common.web;

import org.springframework.http.HttpStatus;

import java.util.List;

/** Erro HTTP de negócio → problem+json (RFC 7807) pelo {@link ProblemDetailsAdvice}. */
public class ApiException extends RuntimeException {

    public record FieldError(String field, String message) {}

    private final HttpStatus status;
    private final String title;
    private final List<FieldError> errors;

    public ApiException(HttpStatus status, String title, String detail, List<FieldError> errors) {
        super(detail);
        this.status = status;
        this.title = title;
        this.errors = errors == null ? List.of() : List.copyOf(errors);
    }

    public ApiException(HttpStatus status, String title, String detail) {
        this(status, title, detail, List.of());
    }

    public static ApiException notFound(String detail) {
        return new ApiException(HttpStatus.NOT_FOUND, "Not Found", detail);
    }

    public static ApiException badRequest(String detail, List<FieldError> errors) {
        return new ApiException(HttpStatus.BAD_REQUEST, "Bad Request", detail, errors);
    }

    public HttpStatus status() {
        return status;
    }

    public String title() {
        return title;
    }

    public List<FieldError> errors() {
        return errors;
    }
}
