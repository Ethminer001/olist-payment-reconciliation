import os, urllib.request, csv
from collections import Counter

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
URLS = {
    "orders.csv": "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/olist_orders_dataset.csv",
    "order_items.csv": "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/olist_order_items_dataset.csv",
    "order_payments.csv": "https://raw.githubusercontent.com/olist/work-at-olist-data/master/datasets/olist_order_payments_dataset.csv",
}

os.makedirs(DATA_DIR, exist_ok=True)
for fname, url in URLS.items():
    fpath = os.path.join(DATA_DIR, fname)
    if not os.path.exists(fpath):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp, open(fpath, "wb") as out:
            out.write(resp.read())

def read_table(fname):
    with open(os.path.join(DATA_DIR, fname), "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))

orders = read_table("orders.csv")
items = read_table("order_items.csv")
payments = read_table("order_payments.csv")

print("=== 1. TABLE SIZES & COLUMNS ===")
print(f"orders.csv:         {len(orders):>7,} rows | Columns: {list(orders[0].keys())}")
print(f"order_items.csv:    {len(items):>7,} rows | Columns: {list(items[0].keys())}")
print(f"order_payments.csv: {len(payments):>7,} rows | Columns: {list(payments[0].keys())}")

print("\n=== 2. TABLE 1 DATA QUALITY CHECK: orders.csv ===")
order_ids = [r["order_id"] for r in orders]
print(" - Duplicate order_id rows:", len(order_ids) - len(set(order_ids)))
status_counts = Counter(r["order_status"] for r in orders)
print(" - Order statuses:", dict(status_counts))
for col in orders[0].keys():
    nulls = sum(1 for r in orders if not r[col].strip())
    if nulls > 0:
        print(f" - Missing values in '{col}': {nulls:,} ({nulls/len(orders)*100:.2f}%)")
# Check delivered orders missing delivery date or approval date
deliv_no_date = sum(1 for r in orders if r["order_status"] == "delivered" and not r["order_delivered_customer_date"].strip())
deliv_no_appr = sum(1 for r in orders if r["order_status"] == "delivered" and not r["order_approved_at"].strip())
bad_seq_appr = sum(1 for r in orders if r["order_approved_at"] and r["order_purchase_timestamp"] and r["order_approved_at"] < r["order_purchase_timestamp"])
bad_seq_deliv = sum(1 for r in orders if r["order_delivered_customer_date"] and r["order_purchase_timestamp"] and r["order_delivered_customer_date"] < r["order_purchase_timestamp"])
bad_seq_carrier = sum(1 for r in orders if r["order_delivered_customer_date"] and r["order_delivered_carrier_date"] and r["order_delivered_customer_date"] < r["order_delivered_carrier_date"])
print(f" - Delivered orders missing customer delivery date: {deliv_no_date}")
print(f" - Delivered orders missing payment approval date:  {deliv_no_appr}")
print(f" - Timestamp anomaly (delivered to customer BEFORE handed to carrier): {bad_seq_carrier}")

print("\n=== 3. TABLE 2 DATA QUALITY CHECK: order_items.csv ===")
item_keys = [(r["order_id"], r["order_item_id"]) for r in items]
print(" - Duplicate (order_id, order_item_id) rows:", len(item_keys) - len(set(item_keys)))
print(" - Unique order_ids in order_items.csv:", len(set(r["order_id"] for r in items)))
for col in items[0].keys():
    nulls = sum(1 for r in items if not r[col].strip())
    if nulls > 0:
        print(f" - Missing values in '{col}': {nulls:,}")
zero_or_neg_price = sum(1 for r in items if float(r["price"]) <= 0)
neg_freight = sum(1 for r in items if float(r["freight_value"]) < 0)
zero_freight = sum(1 for r in items if float(r["freight_value"]) == 0)
print(f" - Items with price <= 0: {zero_or_neg_price}")
print(f" - Items with negative freight_value (< 0): {neg_freight}")
print(f" - Items with zero freight_value (== 0, free shipping): {zero_freight:,}")

print("\n=== 4. TABLE 3 DATA QUALITY CHECK: order_payments.csv ===")
pay_keys = [(r["order_id"], r["payment_sequential"]) for r in payments]
print(" - Duplicate (order_id, payment_sequential) rows:", len(pay_keys) - len(set(pay_keys)))
print(" - Unique order_ids in order_payments.csv:", len(set(r["order_id"] for r in payments)))
pay_types = Counter(r["payment_type"] for r in payments)
print(" - Payment types:", dict(pay_types))
zero_pay = [r for r in payments if float(r["payment_value"]) == 0]
neg_pay = [r for r in payments if float(r["payment_value"]) < 0]
zero_inst = [r for r in payments if int(r["payment_installments"]) <= 0]
print(f" - Payment rows with payment_value == $0.00: {len(zero_pay)} (types: {dict(Counter(r['payment_type'] for r in zero_pay))})")
print(f" - Payment rows with negative payment_value (< 0): {len(neg_pay)}")
print(f" - Payment rows with payment_installments == 0: {len(zero_inst)}")
