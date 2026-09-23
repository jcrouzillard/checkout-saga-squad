-- D1 / ADR-006: GET /orders?customerId= ordenado por created_at desc, order_id desc
CREATE INDEX IF NOT EXISTS idx_orders_customer_created ON orders (customer_id, created_at DESC);
