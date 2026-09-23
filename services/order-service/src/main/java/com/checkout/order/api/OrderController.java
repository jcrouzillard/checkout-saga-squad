package com.checkout.order.api;

import com.checkout.common.web.ApiException;
import com.checkout.common.web.CorrelationIdFilter;
import com.checkout.order.domain.OrderRecord;
import com.checkout.order.domain.OrderRepository;
import com.checkout.order.domain.OrderService;
import com.checkout.order.messaging.OrderPayloads.Line;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.net.URI;
import java.time.Instant;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.UUID;

@RestController
@RequestMapping("/orders")
public class OrderController {

    public record CreateOrderResponse(UUID orderId, UUID sagaId, String status, Map<String, String> links) {}

    public record HistoryView(String step, String status, int attempt, String detail, Instant at) {}

    public record OrderView(UUID orderId, UUID sagaId, String customerId, String status, String deliveryType,
                            BigDecimal totalAmount, String currency, List<Line> items, JsonNode shippingAddress,
                            UUID paymentId, UUID shipmentId, String trackingCode, String cancellationReason,
                            Instant createdAt, Instant updatedAt, List<HistoryView> history) {}

    private final OrderService service;
    private final OrderRepository repo;
    private final ObjectMapper mapper;

    public OrderController(OrderService service, OrderRepository repo, ObjectMapper mapper) {
        this.service = service;
        this.repo = repo;
        this.mapper = mapper;
    }

    @PostMapping
    public ResponseEntity<CreateOrderResponse> create(
            @RequestHeader(value = "Idempotency-Key", required = false) String idempotencyKey,
            @RequestBody(required = false) JsonNode body, HttpServletRequest request) {
        OrderService.CreateResult result = service.create(idempotencyKey, body, CorrelationIdFilter.current(request));
        OrderRecord o = result.order();
        String self = "/orders/" + o.orderId();
        CreateOrderResponse resp = new CreateOrderResponse(o.orderId(), o.sagaId(), OrderRecord.PENDING,
                Map.of("self", self));
        if (result.replayed()) {
            return ResponseEntity.ok().header("Idempotent-Replayed", "true").location(URI.create(self)).body(resp);
        }
        return ResponseEntity.status(HttpStatus.ACCEPTED).location(URI.create(self)).body(resp);
    }

    public static final int DEFAULT_LIMIT = 50;
    public static final int MAX_LIMIT = 200;

    /** D1 (api.md §1, ADR-006): lista os pedidos de um cliente; só lê o database orders. */
    @GetMapping
    public List<OrderRepository.OrderSummary> listByCustomer(@RequestParam(required = false) String customerId,
                                                             @RequestParam(required = false) String limit) {
        List<ApiException.FieldError> errors = new ArrayList<>();
        // Sem trim: espaços nas pontas são rejeitados (parecer G1-D1).
        if (customerId == null || customerId.isEmpty() || customerId.length() > 100) {
            errors.add(new ApiException.FieldError("customerId", "obrigatório (1–100 caracteres)"));
        } else if (!customerId.equals(customerId.strip())) {
            errors.add(new ApiException.FieldError("customerId", "não pode ter espaços nas pontas"));
        }
        int n = DEFAULT_LIMIT;
        if (limit != null) {
            try {
                n = Integer.parseInt(limit);
            } catch (NumberFormatException e) {
                n = -1;
            }
            if (n < 1 || n > MAX_LIMIT) {
                errors.add(new ApiException.FieldError("limit", "inteiro entre 1 e " + MAX_LIMIT));
            }
        }
        if (!errors.isEmpty()) {
            String detail = errors.get(0).field().equals("customerId") ? "customerId é obrigatório e deve ter 1–100 "
                    + "caracteres sem espaços nas pontas" : "limit deve ser um inteiro entre 1 e " + MAX_LIMIT;
            throw ApiException.badRequest(detail, errors);
        }
        return repo.findByCustomer(customerId, n);
    }

    @GetMapping("/{orderId}")
    public OrderView get(@PathVariable UUID orderId) {
        OrderRecord o = repo.findById(orderId)
                .orElseThrow(() -> ApiException.notFound("Pedido " + orderId + " não encontrado"));
        List<HistoryView> history = repo.history(orderId).stream()
                .map(h -> new HistoryView(h.step(), h.status(), h.attempt(), h.detail(), h.at())).toList();
        return new OrderView(o.orderId(), o.sagaId(), o.customerId(), o.status(), o.deliveryType(), o.totalAmount(),
                o.currency(), repo.items(orderId), readTree(o.shippingAddressJson()), o.paymentId(), o.shipmentId(),
                o.trackingCode(), o.cancellationReason(), o.createdAt(), o.updatedAt(), history);
    }

    private JsonNode readTree(String json) {
        try {
            return json == null ? null : mapper.readTree(json);
        } catch (Exception e) {
            return null;
        }
    }
}
