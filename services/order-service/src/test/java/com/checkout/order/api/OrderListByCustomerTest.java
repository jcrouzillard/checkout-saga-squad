package com.checkout.order.api;

import com.checkout.common.web.ProblemDetailsAdvice;
import com.checkout.order.domain.OrderRepository;
import com.checkout.order.domain.OrderRepository.OrderSummary;
import com.checkout.order.domain.OrderService;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.WebMvcTest;
import org.springframework.context.annotation.Import;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

import java.math.BigDecimal;
import java.time.Instant;
import java.util.List;
import java.util.UUID;

import static org.mockito.ArgumentMatchers.anyInt;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.content;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

/** Slice do endpoint D1 GET /orders?customerId=&limit= (api.md §1, ADR-006). */
@WebMvcTest(OrderController.class)
@Import(ProblemDetailsAdvice.class)
class OrderListByCustomerTest {

    @Autowired
    MockMvc mvc;

    @MockitoBean
    OrderRepository repo;

    @MockitoBean
    OrderService service;

    @Test
    void returnsOrdersInRepositoryOrderWithDefaultLimit50() throws Exception {
        UUID newer = UUID.randomUUID();
        UUID older = UUID.randomUUID();
        when(repo.findByCustomer("c-123", 50)).thenReturn(List.of(
                new OrderSummary(newer, "CANCELED", new BigDecimal("99.80"), "PHYSICAL",
                        Instant.parse("2026-09-23T14:05:12.100Z"), "PAYMENT_DECLINED"),
                new OrderSummary(older, "CONFIRMED", new BigDecimal("49.90"), "DIGITAL",
                        Instant.parse("2026-09-23T13:58:01Z"), null)));

        mvc.perform(get("/orders").param("customerId", "c-123"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.length()").value(2))
                .andExpect(jsonPath("$[0].orderId").value(newer.toString()))
                .andExpect(jsonPath("$[0].status").value("CANCELED"))
                .andExpect(jsonPath("$[0].cancellationReason").value("PAYMENT_DECLINED"))
                .andExpect(jsonPath("$[0].totalAmount").value(99.80))
                .andExpect(jsonPath("$[0].deliveryType").value("PHYSICAL"))
                .andExpect(jsonPath("$[0].createdAt").value("2026-09-23T14:05:12.100Z"))
                .andExpect(jsonPath("$[1].orderId").value(older.toString()))
                .andExpect(jsonPath("$[1].cancellationReason").doesNotExist());
        verify(repo).findByCustomer("c-123", 50);
    }

    @Test
    void unknownCustomerReturnsEmptyArray() throws Exception {
        when(repo.findByCustomer("ninguem", 50)).thenReturn(List.of());
        mvc.perform(get("/orders").param("customerId", "ninguem"))
                .andExpect(status().isOk())
                .andExpect(content().json("[]"));
    }

    @Test
    void explicitLimitIsPassedThrough() throws Exception {
        when(repo.findByCustomer("c-1", 200)).thenReturn(List.of());
        mvc.perform(get("/orders").param("customerId", "c-1").param("limit", "200")).andExpect(status().isOk());
        verify(repo).findByCustomer("c-1", 200);
    }

    @Test
    void missingOrBlankCustomerIdIs400() throws Exception {
        mvc.perform(get("/orders"))
                .andExpect(status().isBadRequest())
                .andExpect(content().contentTypeCompatibleWith("application/problem+json"))
                .andExpect(jsonPath("$.errors[0].field").value("customerId"));
        mvc.perform(get("/orders").param("customerId", "")).andExpect(status().isBadRequest());
        mvc.perform(get("/orders").param("customerId", "x".repeat(101))).andExpect(status().isBadRequest());
        verify(repo, never()).findByCustomer(anyString(), anyInt());
    }

    @Test
    void customerIdWithSurroundingSpacesIs400WithoutTrim() throws Exception {
        mvc.perform(get("/orders").param("customerId", " c-123"))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.errors[0].field").value("customerId"));
        mvc.perform(get("/orders").param("customerId", "c-123 ")).andExpect(status().isBadRequest());
        verify(repo, never()).findByCustomer(anyString(), anyInt());
    }

    @Test
    void invalidLimitIs400() throws Exception {
        for (String limit : List.of("0", "201", "-1", "abc", "1.5")) {
            mvc.perform(get("/orders").param("customerId", "c-1").param("limit", limit))
                    .andExpect(status().isBadRequest())
                    .andExpect(jsonPath("$.errors[0].field").value("limit"));
        }
        verify(repo, never()).findByCustomer(anyString(), anyInt());
    }
}
