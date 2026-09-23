package com.checkout.shipping.domain;

import com.fasterxml.jackson.annotation.JsonIgnore;
import com.fasterxml.jackson.annotation.JsonIgnoreProperties;

/** Endereço de entrega (events.md §4.1/§4.5). */
@JsonIgnoreProperties(ignoreUnknown = true)
public record Address(String street, String number, String complement, String city, String state, String zipCode,
                      String country) {

    /** Todos os campos obrigatórios, exceto {@code complement} (api.md §1). */
    @JsonIgnore
    public boolean isValid() {
        return notBlank(street) && notBlank(number) && notBlank(city) && notBlank(state) && notBlank(zipCode)
                && notBlank(country);
    }

    private static boolean notBlank(String s) {
        return s != null && !s.isBlank();
    }
}
