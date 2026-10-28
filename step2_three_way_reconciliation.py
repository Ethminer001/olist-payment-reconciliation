import os, csv
from collections import defaultdict, Counter

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def read_table(fname):
    with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

orders = read_table("orders.csv")
items = read_table("order_items.csv")
payments = read_table("order_payments.csv")

# 1. Clean & aggregate order_items by order_id (rounding to 2 decimal places)
invoice_by_order = {}
for r in items:
    oid = r["order_id"]
    if oid not in invoice_by_order:
        invoice_by_order[oid] = {"item_count": 0, "price_sum": 0.0, "freight_sum": 0.0, "invoice_total": 0.0}
    price = round(float(r["price"]), 2)
    freight = round(float(r["freight_value"]), 2)
    invoice_by_order[oid]["item_count"] += 1
    invoice_by_order[oid]["price_sum"] = round(invoice_by_order[oid]["price_sum"] + price, 2)
    invoice_by_order[oid]["freight_sum"] = round(invoice_by_order[oid]["freight_sum"] + freight, 2)
    invoice_by_order[oid]["invoice_total"] = round(invoice_by_order[oid]["price_sum"] + invoice_by_order[oid]["freight_sum"], 2)

# 2. Clean & aggregate order_payments by order_id (rounding to 2 decimal places)
pay_by_order = {}
for r in payments:
    oid = r["order_id"]
    if oid not in pay_by_order:
        pay_by_order[oid] = {
            "pay_rows": 0,
            "paid_total": 0.0,
            "methods": set(),
            "max_installments": 0,
            "zero_val_rows": 0
        }
    val = round(float(r["payment_value"]), 2)
    inst = int(r["payment_installments"])
    pay_by_order[oid]["pay_rows"] += 1
    pay_by_order[oid]["paid_total"] = round(pay_by_order[oid]["paid_total"] + val, 2)
    pay_by_order[oid]["methods"].add(r["payment_type"])
    if inst > pay_by_order[oid]["max_installments"]:
        pay_by_order[oid]["max_installments"] = inst
    if val == 0.0:
        pay_by_order[oid]["zero_val_rows"] += 1

# 3. Three-Way Reconciliation Join across all 99,441 orders
print("=== STAGE 2: THREE-WAY RECONCILIATION RESULTS ===")

# Check A: Orders missing from Payment Gateway table completely
missing_from_payments = [o for o in orders if o["order_id"] not in pay_by_order]
print(f"\n[CHECK A] Orders in Order System with ZERO record in Payment Gateway: {len(missing_from_payments)}")
for o in missing_from_payments:
    oid = o["order_id"]
    inv = invoice_by_order.get(oid, {})
    print(f"  -> order_id={oid} | status={o['order_status']} | items={inv.get('item_count',0)} | invoice_total=R${inv.get('invoice_total',0):.2f}")

# Check B: Orders with Payment Recorded (> R$0.00) but ZERO items in Invoice/Billing System (Orphan Payments)
orphan_payments = []
for o in orders:
    oid = o["order_id"]
    p = pay_by_order.get(oid)
    if p and p["paid_total"] > 0 and oid not in invoice_by_order:
        orphan_payments.append((o, p))

print(f"\n[CHECK B] Orders with Payment Recorded (> R$0) but ZERO items in Invoice System: {len(orphan_payments)}")
orphan_total_val = sum(p["paid_total"] for _, p in orphan_payments)
orphan_by_status = Counter(o["order_status"] for o, _ in orphan_payments)
orphan_val_by_status = defaultdict(float)
for o, p in orphan_payments:
    orphan_val_by_status[o["order_status"]] = round(orphan_val_by_status[o["order_status"]] + p["paid_total"], 2)
print(f"  -> Total money recorded on itemless orders: R$ {orphan_total_val:,.2f}")
for st, cnt in orphan_by_status.most_common():
    print(f"     * status='{st}': {cnt} orders (R$ {orphan_val_by_status[st]:,.2f})")

# Check C: Orders present in BOTH Invoice System and Payment Gateway where Paid != Invoice Total
# Use a strict > R$0.05 threshold to rule out 1-2 cent rounding noise, and also report exact 1-5 cent rounding cases separately
cent_rounding_diff = [] # 0.01 to 0.05 diff
underpaid_orders = []   # paid < invoice - 0.05
overpaid_orders = []    # paid > invoice + 0.05

for o in orders:
    oid = o["order_id"]
    if oid in invoice_by_order and oid in pay_by_order:
        inv_tot = invoice_by_order[oid]["invoice_total"]
        paid_tot = pay_by_order[oid]["paid_total"]
        diff = round(paid_tot - inv_tot, 2) # negative = underpaid, positive = overpaid
        if 0 < abs(diff) <= 0.05:
            cent_rounding_diff.append((o, invoice_by_order[oid], pay_by_order[oid], diff))
        elif diff < -0.05:
            underpaid_orders.append((o, invoice_by_order[oid], pay_by_order[oid], diff))
        elif diff > 0.05:
            overpaid_orders.append((o, invoice_by_order[oid], pay_by_order[oid], diff))

print(f"\n[CHECK C] Invoice Total vs. Payment Gateway Amount Mismatches (for the {len(set(invoice_by_order).intersection(pay_by_order)):,} orders in both tables):")
print(f"  -> Minor 1-to-5 cent rounding differences ($0.01–$0.05): {len(cent_rounding_diff)} orders (filtered out as rounding noise)")
print(f"  -> Underpaid Orders (Gateway collected LESS than Invoice by > R$0.05): {len(underpaid_orders)} orders")
under_shortfall = sum(abs(d) for _, _, _, d in underpaid_orders)
under_by_status = Counter(o["order_status"] for o, _, _, _ in underpaid_orders)
under_by_method = Counter("+".join(sorted(p["methods"])) for _, _, p, _ in underpaid_orders)
print(f"     * Total Under-Collection Shortfall: R$ {under_shortfall:,.2f}")
print(f"     * By Order Status: {dict(under_by_status)}")
print(f"     * By Payment Method: {dict(under_by_method)}")
for o, inv, p, d in sorted(underpaid_orders, key=lambda x: x[3])[:5]:
    print(f"     * Top example: order_id={o['order_id'][:12]}... | status={o['order_status']} | Invoice=R${inv['invoice_total']:.2f} | Paid=R${p['paid_total']:.2f} | Shortfall=R${d:.2f} | methods={sorted(p['methods'])}")

print(f"  -> Overpaid Orders (Gateway collected MORE than Invoice by > R$0.05): {len(overpaid_orders)} orders")
over_excess = sum(d for _, _, _, d in overpaid_orders)
over_1inst = [x for x in overpaid_orders if x[2]["max_installments"] <= 1]
over_multi = [x for x in overpaid_orders if x[2]["max_installments"] > 1]
print(f"     * Total Excess Collected: R$ {over_excess:,.2f}")
print(f"     * Single-Installment (1x) Overpayments (pure overcharge, cannot be installment interest): {len(over_1inst)} orders (R$ {sum(x[3] for x in over_1inst):,.2f})")
print(f"     * Multi-Installment (>1x) Overpayments (likely installment interest/fees): {len(over_multi)} orders (R$ {sum(x[3] for x in over_multi):,.2f})")

# Check D: Canceled or Unavailable Orders with Recorded Payments (> R$0.00)
unverified_cancel_unavail = []
for o in orders:
    oid = o["order_id"]
    if o["order_status"] in ["canceled", "unavailable"] and oid in pay_by_order and pay_by_order[oid]["paid_total"] > 0:
        has_items = oid in invoice_by_order
        unverified_cancel_unavail.append((o, pay_by_order[oid], has_items))

print(f"\n[CHECK D] Canceled or Unavailable Orders with Recorded Payment (> R$0.00) Requiring Refund Verification: {len(unverified_cancel_unavail)}")
c_by_st = Counter((o["order_status"], has_i) for o, _, has_i in unverified_cancel_unavail)
for (st, has_i), cnt in c_by_st.items():
    val = sum(p["paid_total"] for o, p, hi in unverified_cancel_unavail if o["order_status"] == st and hi == has_i)
    print(f"  -> status='{st}', has_invoice_items={has_i}: {cnt} orders (R$ {val:,.2f})")
