package com.checkout.order.api;

import com.fasterxml.jackson.databind.JsonNode;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;

/**
 * SHA-256 do JSON canônico (chaves ordenadas, sem espaços, números normalizados: 49.9 == 49.90)
 * usado para decidir 200 (replay) × 409 (corpo diferente) com o mesmo Idempotency-Key.
 */
public final class RequestHasher {
    private RequestHasher() {}

    public static String sha256(JsonNode body) {
        StringBuilder sb = new StringBuilder();
        canonical(body, sb);
        try {
            byte[] d = MessageDigest.getInstance("SHA-256").digest(sb.toString().getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(d);
        } catch (NoSuchAlgorithmException e) {
            throw new IllegalStateException(e);
        }
    }

    static void canonical(JsonNode n, StringBuilder sb) {
        if (n == null || n.isNull() || n.isMissingNode()) {
            sb.append("null");
        } else if (n.isObject()) {
            List<String> names = new ArrayList<>();
            n.fieldNames().forEachRemaining(names::add);
            names.sort(null);
            sb.append('{');
            boolean first = true;
            for (String name : names) {
                if (!first) sb.append(',');
                first = false;
                sb.append(quote(name)).append(':');
                canonical(n.get(name), sb);
            }
            sb.append('}');
        } else if (n.isArray()) {
            sb.append('[');
            for (int i = 0; i < n.size(); i++) {
                if (i > 0) sb.append(',');
                canonical(n.get(i), sb);
            }
            sb.append(']');
        } else if (n.isNumber()) {
            BigDecimal v = n.decimalValue();
            sb.append(v.signum() == 0 ? "0" : v.stripTrailingZeros().toPlainString());
        } else if (n.isTextual()) {
            sb.append(quote(n.textValue()));
        } else {
            sb.append(n.toString());
        }
    }

    private static String quote(String s) {
        return com.fasterxml.jackson.databind.node.TextNode.valueOf(s).toString();
    }
}
