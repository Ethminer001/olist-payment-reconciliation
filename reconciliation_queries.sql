-- ============================================================================
-- THREE-WAY PAYMENT GATEWAY & ORDER LEDGER RECONCILIATION (SQL)
-- Tables: orders (99,441), order_items (112,650), order_payments (103,886)
-- ============================================================================

-- STEP 1: Aggregate Billing Table (order_items) to 1 row per order_id
WITH invoice_ledger AS (
    SELECT
        order_id,
        COUNT(*) AS item_count,
        ROUND(SUM(ROUND(CAST(price AS REAL), 2)), 2) AS price_total_brl,
        ROUND(SUM(ROUND(CAST(freight_value AS REAL), 2)), 2) AS freight_total_brl,
        ROUND(SUM(ROUND(CAST(price AS REAL), 2) + ROUND(CAST(freight_value AS REAL), 2)), 2) AS invoice_total_brl,
        MAX(CASE WHEN CAST(price AS REAL) = CAST(freight_value AS REAL) THEN 1 ELSE 0 END) AS has_freight_eq_price_bug
    FROM order_items
    GROUP BY order_id
),

-- STEP 2: Aggregate Payment Gateway Table (order_payments) to 1 row per order_id
payment_ledger AS (
    SELECT
        order_id,
        COUNT(*) AS payment_rows,
        ROUND(SUM(ROUND(CAST(payment_value AS REAL), 2)), 2) AS payment_total_brl,
        MAX(CAST(payment_installments AS INTEGER)) AS max_installments,
        MIN(CAST(payment_installments AS INTEGER)) AS min_installments,
        GROUP_CONCAT(DISTINCT payment_type) AS payment_methods
    FROM order_payments
    GROUP BY order_id
),

-- STEP 3: Three-Way Left Join from Master Order Book (orders)
three_way_recon AS (
    SELECT
        o.order_id,
        o.order_status,
        SUBSTR(o.order_purchase_timestamp, 1, 10) AS purchase_date,
        COALESCE(i.item_count, 0) AS item_count,
        COALESCE(i.price_total_brl, 0.0) AS price_total_brl,
        COALESCE(i.freight_total_brl, 0.0) AS freight_total_brl,
        COALESCE(i.invoice_total_brl, 0.0) AS invoice_total_brl,
        COALESCE(p.payment_rows, 0) AS payment_rows,
        COALESCE(p.payment_total_brl, 0.0) AS payment_total_brl,
        ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2) AS variance_brl,
        COALESCE(p.max_installments, 0) AS max_installments,
        COALESCE(p.min_installments, 1) AS min_installments,
        COALESCE(p.payment_methods, 'NONE') AS payment_methods,
        COALESCE(i.has_freight_eq_price_bug, 0) AS has_freight_eq_price_bug,
        CASE
            WHEN p.order_id IS NULL THEN 'E1_MISSING_GATEWAY_RECORD'
            WHEN o.order_status IN ('canceled', 'unavailable') AND COALESCE(p.payment_total_brl, 0) = 0 THEN 'INFO_3_ABORTED_ZERO_PAYMENT_CANCELED'
            WHEN o.order_status IN ('canceled', 'unavailable') AND COALESCE(i.item_count, 0) = 0 THEN 'E6_CANCELED_NO_ITEMS_REFUND_CHECK'
            WHEN o.order_status IN ('canceled', 'unavailable') AND COALESCE(i.item_count, 0) > 0 THEN 'E7_CANCELED_WITH_ITEMS_REFUND_CHECK'
            WHEN COALESCE(i.item_count, 0) = 0 AND COALESCE(p.payment_total_brl, 0) > 0 THEN 'E2_ACTIVE_ORDER_MISSING_ITEMS'
            WHEN ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2) < -0.05
                 AND COALESCE(i.has_freight_eq_price_bug, 0) = 1 THEN 'E3_BILLING_FREIGHT_COPY_BUG'
            WHEN ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2) < -0.05
                 AND ABS(ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2)) <= 0.10
                 AND COALESCE(i.item_count, 0) >= 10 THEN 'INFO_2_CENT_ROUNDING_NOISE'
            WHEN ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2) < -0.05 THEN 'E4_UNRECORDED_CHECKOUT_DISCOUNT'
            WHEN ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2) > 0.05
                 AND COALESCE(p.max_installments, 0) <= 1 THEN 'E5_SINGLE_PAYMENT_OVERCHARGE'
            WHEN ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2) > 0.05 THEN 'INFO_1_MULTI_INSTALLMENT_INTEREST'
            WHEN (o.order_status = 'delivered' AND TRIM(o.order_approved_at) = '')
                 OR (o.order_status = 'delivered' AND TRIM(o.order_delivered_customer_date) = '')
                 OR (TRIM(o.order_delivered_customer_date) != '' AND TRIM(o.order_delivered_carrier_date) != '' AND o.order_delivered_customer_date < o.order_delivered_carrier_date)
                 OR COALESCE(p.min_installments, 1) = 0 THEN 'E8_METADATA_TIMESTAMP_OR_INSTALLMENT_BUG'
            WHEN ABS(ROUND(COALESCE(p.payment_total_brl, 0.0) - COALESCE(i.invoice_total_brl, 0.0), 2)) BETWEEN 0.01 AND 0.05 THEN 'INFO_2_CENT_ROUNDING_NOISE'
            ELSE 'CLEAN_RECONCILED_ORDER'
        END AS category_code
    FROM orders o
    LEFT JOIN invoice_ledger i ON o.order_id = i.order_id
    LEFT JOIN payment_ledger p ON o.order_id = p.order_id
)

-- STEP 4: Output Reconciliation Summary by Category
SELECT
    category_code,
    COUNT(*) AS order_count,
    ROUND(SUM(invoice_total_brl), 2) AS invoice_total_brl,
    ROUND(SUM(payment_total_brl), 2) AS payment_total_brl
FROM three_way_recon
GROUP BY category_code
ORDER BY category_code;
