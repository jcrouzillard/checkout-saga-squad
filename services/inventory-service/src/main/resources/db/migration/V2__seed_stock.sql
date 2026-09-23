-- Seeds de estoque (docs/contracts/api.md §4)
INSERT INTO stock (sku, available, reserved) VALUES
    ('SKU-BOOK-001',    1000,   0),
    ('SKU-PHONE-001',   100,    0),
    ('SKU-EBOOK-001',   100000, 0),
    ('SKU-COURSE-001',  100000, 0),
    ('SKU-LIMITED-001', 1,      0)
ON CONFLICT (sku) DO NOTHING;
