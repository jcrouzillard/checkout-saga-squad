package com.checkout.common.web;

import jakarta.servlet.http.HttpServletRequest;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ProblemDetail;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MissingRequestHeaderException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import java.net.URI;
import java.util.List;

/** Erros no formato RFC 7807 {@code application/problem+json} (api.md, cabeçalho). */
@RestControllerAdvice
@Order(Ordered.LOWEST_PRECEDENCE)
public class ProblemDetailsAdvice {

    private static final Logger log = LoggerFactory.getLogger(ProblemDetailsAdvice.class);

    @ExceptionHandler(ApiException.class)
    public ResponseEntity<ProblemDetail> api(ApiException e, HttpServletRequest req) {
        return problem(e.status(), e.title(), e.getMessage(), e.errors(), req);
    }

    @ExceptionHandler(HttpMessageNotReadableException.class)
    public ResponseEntity<ProblemDetail> unreadable(HttpMessageNotReadableException e, HttpServletRequest req) {
        return problem(HttpStatus.BAD_REQUEST, "Bad Request", "Corpo da requisição inválido ou ausente", List.of(), req);
    }

    @ExceptionHandler(MissingRequestHeaderException.class)
    public ResponseEntity<ProblemDetail> missingHeader(MissingRequestHeaderException e, HttpServletRequest req) {
        return problem(HttpStatus.BAD_REQUEST, "Bad Request", "Header obrigatório ausente: " + e.getHeaderName(),
                List.of(new ApiException.FieldError(e.getHeaderName(), "obrigatório")), req);
    }

    @ExceptionHandler(MethodArgumentTypeMismatchException.class)
    public ResponseEntity<ProblemDetail> typeMismatch(MethodArgumentTypeMismatchException e, HttpServletRequest req) {
        return problem(HttpStatus.BAD_REQUEST, "Bad Request", "Parâmetro inválido: " + e.getName(),
                List.of(new ApiException.FieldError(e.getName(), "formato inválido")), req);
    }

    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<ProblemDetail> noResource(NoResourceFoundException e, HttpServletRequest req) {
        return problem(HttpStatus.NOT_FOUND, "Not Found", "Recurso não encontrado", List.of(), req);
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<ProblemDetail> unexpected(Exception e, HttpServletRequest req) {
        log.error("Erro inesperado em {} {}", req.getMethod(), req.getRequestURI(), e);
        return problem(HttpStatus.INTERNAL_SERVER_ERROR, "Internal Server Error", "Erro inesperado", List.of(), req);
    }

    public static ResponseEntity<ProblemDetail> problem(HttpStatus status, String title, String detail,
                                                        List<ApiException.FieldError> errors, HttpServletRequest req) {
        ProblemDetail pd = ProblemDetail.forStatusAndDetail(status, detail);
        pd.setType(URI.create("about:blank"));
        pd.setTitle(title);
        pd.setInstance(URI.create(req.getRequestURI()));
        if (errors != null && !errors.isEmpty()) {
            pd.setProperty("errors", errors);
        }
        return ResponseEntity.status(status).contentType(MediaType.APPLICATION_PROBLEM_JSON).body(pd);
    }
}
