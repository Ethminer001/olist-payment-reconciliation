import os, csv
from collections import defaultdict, Counter

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

def read_table(fname):
    with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

orders = {r["order_id"]: r for r in read_table("orders.csv")}
items_raw = read_table("order_items.csv")
payments_raw = read_table("order_payments.csv")

items_by_oid = defaultdict(list)
for r in items_raw:
    items_by_oid[r["order_id"]].append(r)

pays_by_oid = defaultdict(list)
for r in payments_raw:
    pays_by_oid[r["order_id"]].append(r)

print("=== DEEP DIVE 1: THE 1 DELIVERED ORDER MISSING FROM PAYMENT GATEWAY ===")
oid_missing = "bfbd0f9bdef84302105ad712db648a6c"
print("Order record:", orders[oid_missing])
print("Items records:", items_by_oid[oid_missing])

print("\n=== DEEP DIVE 2: WHY WERE THE 77 DELIVERED ORDERS UNDERPAID (paid < invoice - 0.05)? ===")
underpaid_patterns = Counter()
underpaid_details = []
for oid, item_list in items_by_oid.items():
    if oid not in pays_by_oid:
        continue
    p_list = pays_by_oid[oid]
    price_sum = round(sum(round(float(x["price"]), 2) for x in item_list), 2)
    freight_sum = round(sum(round(float(x["freight_value"]), 2) for x in item_list), 2)
    inv_total = round(price_sum + freight_sum, 2)
    paid_total = round(sum(round(float(x["payment_value"]), 2) for x in p_list), 2)
    diff = round(paid_total - inv_total, 2)
    if diff < -0.05:
        n_items = len(item_list)
        shortfall = round( inv_total - paid_total, 2)
        # Check exact hypotheses:
        # H1: Did customer pay ONLY price_sum (freight_sum was not charged)?
        # H2: In a multi-item order, does paid_total equal (or closely match) ONLY 1 item (or subset of items) instead of all items?
        # H3: Did one of the payment rows have payment_value == 0?
        item_totals = [round(float(x["price"]) + float(x["freight_value"]), 2) for x in item_list]
        item_prices = [round(float(x["price"]), 2) for x in item_list]
        if abs(paid_total - price_sum) <= 0.05:
            pat = "Freight Not Charged (Paid == Item Price Only)"
        elif n_items > 1 and any(abs(paid_total - it) <= 0.05 for it in item_totals):
            pat = f"Multi-Item Partial Capture (Paid == 1 of {n_items} items)"
        elif n_items > 1 and abs(paid_total - (price_sum / n_items + freight_sum)) <= 1.0:
            pat = "Multi-Item Partial Price Capture"
        elif any(float(x["payment_value"]) == 0 for x in p_list):
            pat = "Has $0.00 Voucher/Payment Row"
        elif n_items > 1:
            pat = f"Multi-Item Partial/Discounted Capture ({n_items} items)"
        else:
            pat = "Single-Item Partial Capture / Unrecorded Discount"
        underpaid_patterns[pat] += 1
        underpaid_details.append((oid, n_items, price_sum, freight_sum, inv_total, paid_total, diff, pat, [x["payment_type"] for x in p_list]))

for pat, cnt in underpaid_patterns.most_common():
    print(f" - {pat}: {cnt} orders")
print("\nSample 12 Underpaid Orders:")
for row in sorted(underpaid_details, key=lambda x: x[6])[:12]:
    oid, n_it, p_s, f_s, inv_t, pd_t, df, pat, mths = row
    print(f"  {oid[:10]}.. | items={n_it} | price={p_s:.2f} | freight={f_s:.2f} | inv={inv_t:.2f} | paid={pd_t:.2f} | diff={df:.2f} | {pat} | {mths}")

print("\n=== DEEP DIVE 3: THE 7 SINGLE-INSTALLMENT (1x) OVERPAID ORDERS (> +R$0.05) ===")
for oid, item_list in items_by_oid.items():
    if oid not in pays_by_oid:
        continue
    p_list = pays_by_oid[oid]
    inv_total = round(sum(round(float(x["price"]) + float(x["freight_value"]), 2) for x in item_list), 2)
    paid_total = round(sum(round(float(x["payment_value"]), 2) for x in p_list), 2)
    diff = round(paid_total - inv_total, 2)
    max_inst = max(int(x["payment_installments"]) for x in p_list)
    if diff > 0.05 and max_inst <= 1:
        print(f"  {oid[:12]}.. | status={orders[oid]['order_status']} | items={len(item_list)} | inv={inv_total:.2f} | paid={paid_total:.2f} | diff=+{diff:.2f} | methods={[x['payment_type'] for x in p_list]}")

print("\n=== DEEP DIVE 4: THE 8 ACTIVE/FULFILLED ITEMLESS ORDERS (Shipped / Invoiced / Created with Payment > 0 but 0 Items) ===")
for oid, o in orders.items():
    if oid not in items_by_oid and oid in pays_by_oid:
        paid_total = round(sum(round(float(x["payment_value"]), 2) for x in pays_by_oid[oid]), 2)
        if paid_total > 0 and o["order_status"] not in ["canceled", "unavailable"]:
            print(f"  {oid[:12]}.. | status={o['order_status']} | purchased={o['order_purchase_timestamp']} | approved={o['order_approved_at']} | carrier={o['order_delivered_carrier_date']} | paid=R${paid_total:.2f} | methods={[x['payment_type'] for x in pays_by_oid[oid]]}")

print("\n=== DEEP DIVE 5: HOW DO THE STAGE-1 SINGLE-TABLE BUGS CONNECT TO PAYMENTS & ITEMS? ===")
# 1. 14 delivered orders missing order_approved_at
deliv_no_appr = [o for o in orders.values() if o["order_status"] == "delivered" and not o["order_approved_at"].strip()]
print(f"1. 14 Delivered orders missing order_approved_at:")
print("   Payment methods on these 14 orders:", dict(Counter(pays_by_oid[o["order_id"]][0]["payment_type"] for o in deliv_no_appr)))
print("   Did all 14 have full payment recorded in order_payments?:", all(abs(sum(float(x["payment_value"]) for x in pays_by_oid[o["order_id"]]) - sum(float(x["price"])+float(x["freight_value"]) for x in items_by_oid[o["order_id"]])) <= 0.05 for o in deliv_no_appr))

# 2. 2 credit card rows with payment_installments == 0
zero_inst = [p for p in payments_raw if int(p["payment_installments"]) == 0]
print(f"2. 2 Payment rows with payment_installments == 0:")
for p in zero_inst:
    oid = p["order_id"]
    print(f"   order_id={oid[:12]}.. | status={orders[oid]['order_status']} | type={p['payment_type']} | seq={p['payment_sequential']} | val=R${p['payment_value']} | total_pay_rows={len(pays_by_oid[oid])}")

# 3. 9 payment rows with payment_value == 0.00
zero_val = [p for p in payments_raw if float(p["payment_value"]) == 0]
print(f"3. 9 Payment rows with payment_value == R$ 0.00:")
for p in zero_val:
    oid = p["order_id"]
    tot_p = sum(float(x["payment_value"]) for x in pays_by_oid[oid])
    print(f"   order_id={oid[:12]}.. | status={orders[oid]['order_status']} | row_type={p['payment_type']} | seq={p['payment_sequential']}/{len(pays_by_oid[oid])} | order_total_paid=R${tot_p:.2f}")
