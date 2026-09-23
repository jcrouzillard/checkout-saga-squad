package com.checkout.common.web;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.slf4j.MDC;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.UUID;

/**
 * Header opcional {@code X-Correlation-Id} (UUID) em todas as requisições; gerado se ausente/inválido e ecoado
 * na resposta (api.md). Disponível via {@link #current(HttpServletRequest)} e no MDC {@code correlationId}.
 */
public class CorrelationIdFilter extends OncePerRequestFilter {

    public static final String HEADER = "X-Correlation-Id";
    public static final String ATTRIBUTE = CorrelationIdFilter.class.getName() + ".id";

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
            throws ServletException, IOException {
        UUID id = parse(request.getHeader(HEADER));
        request.setAttribute(ATTRIBUTE, id);
        response.setHeader(HEADER, id.toString());
        MDC.put("correlationId", id.toString());
        try {
            chain.doFilter(request, response);
        } finally {
            MDC.remove("correlationId");
        }
    }

    public static UUID current(HttpServletRequest request) {
        Object v = request.getAttribute(ATTRIBUTE);
        return v instanceof UUID u ? u : UUID.randomUUID();
    }

    private static UUID parse(String value) {
        if (value != null) {
            try {
                return UUID.fromString(value.trim());
            } catch (IllegalArgumentException ignored) {
                // inválido → gera novo
            }
        }
        return UUID.randomUUID();
    }
}
