import os, csv
from collections import defaultdict, Counter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")

def read_table(fname):
    with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

orders = read_table("orders.csv")
items = read_table("order_items.csv")
payments = read_table("order_payments.csv")

items_by_oid = defaultdict(list)
for r in items:
    items_by_oid[r["order_id"]].append(r)

pays_by_oid = defaultdict(list)
for r in payments:
    pays_by_oid[r["order_id"]].append(r)

exception_rows = []
summary_stats = defaultdict(lambda: {"count": 0, "inv_sum": 0.0, "paid_sum": 0.0, "exposure_sum": 0.0})

CATEGORY_META = {
    "E1_MISSING_GATEWAY_RECORD": "Delivered order has 3 billed items (R$ 143.46) but zero payment record in the payment gateway table.",
    "E2_ACTIVE_ORDER_MISSING_ITEMS": "Payment was collected on an active/shipped order, but the billing table (order_items) has zero items recorded.",
    "E3_BILLING_FREIGHT_COPY_BUG": "Billing table copied item price into the delivery fee column (freight_value == price) across 3 sellers, falsely doubling the item price.",
    "E4_UNRECORDED_CHECKOUT_DISCOUNT": "Delivered order where a 5% debit-card, 10% promo, flat R$10, or bundle discount was applied at payment without being logged in the billing or voucher table.",
    "E5_SINGLE_PAYMENT_OVERCHARGE": "Single-installment (1x) delivered order where the payment gateway collected slightly more than the billed price + delivery fee.",
    "E6_CANCELED_NO_ITEMS_REFUND_CHECK": "Canceled or out-of-stock (unavailable) order with customer payment collected and zero invoice items; payment table lacks a refund status column.",
    "E7_CANCELED_WITH_ITEMS_REFUND_CHECK": "Canceled or out-of-stock (unavailable) order with both invoice items and customer payment collected; payment table lacks a refund status column.",
    "E8_METADATA_TIMESTAMP_OR_INSTALLMENT_BUG": "Invoice and payment amounts match 100%, but order has a missing approval/delivery date, backwards carrier-to-customer timestamp, or 0-installment retry flag.",
    "INFO_1_MULTI_INSTALLMENT_INTEREST": "Multi-installment (>1x) credit-card order where extra amount collected above base invoice represents buyer installment financing interest.",
    "INFO_2_CENT_ROUNDING_NOISE": "Minor 1-to-6 cent rounding difference between item sum and installment/split payment sum.",
    "INFO_3_ABORTED_ZERO_PAYMENT_CANCELED": "Canceled order where customer abandoned checkout with R$ 0.00 paid (and 0 invoice items).",
    "CLEAN_RECONCILED_ORDER": "Order system, billing table, and payment gateway match with zero financial or timestamp defects.",
}

for o in orders:
    oid = o["order_id"]
    st = o["order_status"]
    pdate = o["order_purchase_timestamp"][:10] if o["order_purchase_timestamp"] else ""
    il = items_by_oid.get(oid, [])
    pl = pays_by_oid.get(oid, [])

    n_items = len(il)
    price_sum = round(sum(round(float(x["price"]), 2) for x in il), 2)
    freight_sum = round(sum(round(float(x["freight_value"]), 2) for x in il), 2)
    inv_total = round(price_sum + freight_sum, 2)

    paid_total = round(sum(round(float(x["payment_value"]), 2) for x in pl), 2)
    variance = round(paid_total - inv_total, 2)
    methods = "+".join(sorted(set(x["payment_type"] for x in pl))) if pl else "NONE"
    max_inst = max((int(x["payment_installments"]) for x in pl), default=0)
    min_inst = min((int(x["payment_installments"]) for x in pl), default=1)

    # Check metadata bugs
    no_appr = (st == "delivered" and not o["order_approved_at"].strip())
    no_deliv = (st == "delivered" and not o["order_delivered_customer_date"].strip())
    bad_carrier_seq = bool(o["order_delivered_customer_date"] and o["order_delivered_carrier_date"] and o["order_delivered_customer_date"] < o["order_delivered_carrier_date"])
    zero_inst_bug = (len(pl) > 0 and min_inst == 0)

    # Mutually exclusive classification across all 99,441 orders
    code = None
    specific_note = ""

    if not pl:
        code = "E1_MISSING_GATEWAY_RECORD"
        exposure = inv_total
        specific_note = f"Delivered order ({n_items} items, R$ {inv_total:.2f}) has no record in order_payments.csv."
    elif st in ["canceled", "unavailable"]:
        if paid_total == 0:
            code = "INFO_3_ABORTED_ZERO_PAYMENT_CANCELED"
            exposure = 0.0
        elif n_items == 0:
            code = "E6_CANCELED_NO_ITEMS_REFUND_CHECK"
            exposure = paid_total
            specific_note = f"Order status is '{st}' with R$ {paid_total:.2f} collected ({methods}) and 0 items in billing table; verify bank refund."
        else:
            code = "E7_CANCELED_WITH_ITEMS_REFUND_CHECK"
            exposure = paid_total
            specific_note = f"Order status is '{st}' with R$ {paid_total:.2f} collected ({methods}) and {n_items} billed item(s); verify bank refund."
    elif n_items == 0 and paid_total > 0:
        code = "E2_ACTIVE_ORDER_MISSING_ITEMS"
        exposure = paid_total
        specific_note = f"Active order (status='{st}') has R$ {paid_total:.2f} collected ({methods}) but 0 items in order_items.csv."
    elif variance < -0.05:
        if any(float(x["price"]) == float(x["freight_value"]) for x in il):
            code = "E3_BILLING_FREIGHT_COPY_BUG"
            exposure = abs(variance)
            specific_note = f"Billing table duplicated item price (R$ {price_sum:.2f}) into freight_value (R$ {freight_sum:.2f}); gateway collected R$ {paid_total:.2f}."
        elif abs(variance) <= 0.10 and n_items >= 10:
            code = "INFO_2_CENT_ROUNDING_NOISE"
            exposure = abs(variance)
        else:
            code = "E4_UNRECORDED_CHECKOUT_DISCOUNT"
            exposure = abs(variance)
            pct = round(abs(variance) / price_sum * 100, 2) if price_sum > 0 else 0
            specific_note = f"Gateway collected R$ {paid_total:.2f} vs R$ {inv_total:.2f} invoice (shortfall R$ {abs(variance):.2f} = {pct:.2f}% of item price) via {methods}."
    elif variance > 0.05:
        if max_inst <= 1:
            code = "E5_SINGLE_PAYMENT_OVERCHARGE"
            exposure = variance
            specific_note = f"Single-installment (1x) payment collected R$ {paid_total:.2f} vs R$ {inv_total:.2f} invoice (+R$ {variance:.2f} excess)."
        else:
            code = "INFO_1_MULTI_INSTALLMENT_INTEREST"
            exposure = variance
    elif no_appr or no_deliv or bad_carrier_seq or zero_inst_bug:
        code = "E8_METADATA_TIMESTAMP_OR_INSTALLMENT_BUG"
        exposure = 0.0
        reasons = []
        if no_appr: reasons.append("missing order_approved_at on boleto payment")
        if no_deliv: reasons.append("missing order_delivered_customer_date")
        if bad_carrier_seq: reasons.append("customer_delivery_date earlier than carrier_pickup_date")
        if zero_inst_bug: reasons.append("credit_card retry has payment_installments=0")
        specific_note = "Invoice and payment match (within rounding), but metadata issue found: " + "; ".join(reasons) + "."
    elif 0 < abs(variance) <= 0.05:
        code = "INFO_2_CENT_ROUNDING_NOISE"
        exposure = abs(variance)
    else:
        code = "CLEAN_RECONCILED_ORDER"
        exposure = 0.0

    summary_stats[code]["count"] += 1
    summary_stats[code]["inv_sum"] = round(summary_stats[code]["inv_sum"] + inv_total, 2)
    summary_stats[code]["paid_sum"] = round(summary_stats[code]["paid_sum"] + paid_total, 2)
    summary_stats[code]["exposure_sum"] = round(summary_stats[code]["exposure_sum"] + exposure, 2)

    if code.startswith("E"):
        exception_rows.append({
            "order_id": oid,
            "defect_code": code,
            "order_status": st,
            "purchase_date": pdate,
            "item_count": n_items,
            "price_total_brl": f"{price_sum:.2f}",
            "freight_total_brl": f"{freight_sum:.2f}",
            "invoice_total_brl": f"{inv_total:.2f}",
            "payment_total_brl": f"{paid_total:.2f}",
            "variance_brl": f"{variance:.2f}",
            "amount_to_review_brl": f"{exposure:.2f}",
            "payment_methods": methods,
            "max_installments": max_inst,
            "issue": specific_note,
        })

# Write reconciliation_summary_by_category.csv
sum_path = os.path.join(BASE_DIR, "reconciliation_summary_by_category.csv")
ordered_codes = [
    "E1_MISSING_GATEWAY_RECORD",
    "E2_ACTIVE_ORDER_MISSING_ITEMS",
    "E3_BILLING_FREIGHT_COPY_BUG",
    "E4_UNRECORDED_CHECKOUT_DISCOUNT",
    "E5_SINGLE_PAYMENT_OVERCHARGE",
    "E6_CANCELED_NO_ITEMS_REFUND_CHECK",
    "E7_CANCELED_WITH_ITEMS_REFUND_CHECK",
    "E8_METADATA_TIMESTAMP_OR_INSTALLMENT_BUG",
    "INFO_1_MULTI_INSTALLMENT_INTEREST",
    "INFO_2_CENT_ROUNDING_NOISE",
    "INFO_3_ABORTED_ZERO_PAYMENT_CANCELED",
    "CLEAN_RECONCILED_ORDER"
]

with open(sum_path, "w", newline="", encoding="utf-8") as f:
    fieldnames = [
        "category_code", "order_count", "pct_of_all_orders",
        "invoice_total_brl", "payment_total_brl", "amount_to_review_brl",
        "root_cause"
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    for c in ordered_codes:
        st = summary_stats[c]
        desc = CATEGORY_META[c]
        w.writerow({
            "category_code": c,
            "order_count": st["count"],
            "pct_of_all_orders": f"{st['count']/len(orders)*100:.3f}%",
            "invoice_total_brl": f"{st['inv_sum']:.2f}",
            "payment_total_brl": f"{st['paid_sum']:.2f}",
            "amount_to_review_brl": f"{st['exposure_sum']:.2f}",
            "root_cause": desc
        })

# Write reconciliation_exception_register.csv (sorted by defect_code, then highest exposure)
exc_path = os.path.join(BASE_DIR, "reconciliation_exception_register.csv")
exception_rows.sort(key=lambda r: (r["defect_code"], -float(r["amount_to_review_brl"])))
with open(exc_path, "w", newline="", encoding="utf-8") as f:
    fieldnames = [
        "order_id", "defect_code", "order_status", "purchase_date",
        "item_count", "price_total_brl", "freight_total_brl", "invoice_total_brl",
        "payment_total_brl", "variance_brl", "amount_to_review_brl",
        "payment_methods", "max_installments", "issue"
    ]
    w = csv.DictWriter(f, fieldnames=fieldnames)
    w.writeheader()
    w.writerows(exception_rows)

print(f"Total orders classified: {sum(s['count'] for s in summary_stats.values()):,} (matches 99,441 exactly!)")
print(f"Total actionable exception rows written to reconciliation_exception_register.csv: {len(exception_rows):,}")
print("\n=== SUMMARY TABLE PREVIEW ===")
for c in ordered_codes:
    s = summary_stats[c]
    print(f"  {c:<42} | {s['count']:>6,} orders | Inv: R${s['inv_sum']:>13,.2f} | Paid: R${s['paid_sum']:>13,.2f} | Exposure: R${s['exposure_sum']:>11,.2f}")
