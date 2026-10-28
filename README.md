# Payment and order reconciliation on 99,441 Olist orders

An audit of three tables from Olist's public e-commerce data: orders, order items (what was billed) and order payments (what was collected). It is a retrospective check on public data, not a client engagement. Python and SQL.

## Results

- 97,517 of 99,441 orders (98.07%) match across the three tables to the cent.
- 1,370 orders (1.38%) have a real mismatch or a broken record. Each is listed in `reconciliation_exception_register.csv` with its cause.
- 1,231 cancelled or unavailable orders still show a payment (R$ 269,735.11 in total). The payment table has no refund column, so I cannot tell whether the money was returned. These are flagged for a refund check, not counted as losses.
- 63 orders from 3 sellers have the item price copied into the freight column. 58 of them look underpaid, by R$ 4,699.71 in total. The payments fit the price plus a normal freight charge, so the billing table looks wrong, not the payments.
- 18 delivered orders were paid less than billed by R$ 198.57 in total. Nine are exactly 10% off, six debit-card orders are exactly 5% off, one is exactly R$ 10 off, and two are bundle or freight discounts.
- 8 active orders have a payment but no billed items (R$ 915.06). One delivered order (R$ 143.46) has no payment record at all.
- 7 single-payment orders were charged slightly more than billed (R$ 8.49 in total).
- 47 fully paid orders have broken metadata: 14 boleto orders delivered with no approval date, 8 with no delivery date, 23 with a delivery date before the carrier pickup, and 2 card retries recorded with zero installments.
- Not counted as defects: 237 multi-installment orders paid above the billed total (R$ 3,038.96, most likely installment interest), 314 orders off by R$ 0.06 or less, and 3 cancelled orders where the buyer paid nothing.

| Code | Orders | Amount to review (R$) |
|---|---:|---:|
| E1 delivered, no payment record | 1 | 143.46 |
| E2 active order with payment, no items | 8 | 915.06 |
| E3 freight copied from price | 58 | 4,699.71 |
| E4 payment below bill, unrecorded discount | 18 | 198.57 |
| E5 single payment above bill | 7 | 8.49 |
| E6 cancelled, paid, no items | 764 | 161,676.89 |
| E7 cancelled, paid, with items | 467 | 108,058.22 |
| E8 date or installment defects | 47 | 0.00 |
| Clean | 97,517 | |

## Limits

- The payment table has no refund, discount or installment-interest column. Cancelled orders with a payment are flagged for a refund check. A payment above the bill on a multi-installment order is treated as interest. The discount finding rests on exact percentages, not on a discount field.
- Differences of R$ 0.06 or less are treated as rounding.
- The causes are my reading of the patterns in the data. Olist has not confirmed them.
- Each order is classified by its payment pattern first. Five of the 63 copy-bug orders show a small overpayment instead of a shortfall (R$ 1.11 to R$ 2.24): four sit in the installment-interest group and one in the single-payment group. Counting all five as copy-bug orders would raise the flagged total from 1,370 to about 1,375.
- `amount_to_review_brl` is the payment or the gap on a flagged order. It is not a loss figure.

## Data

Olist public orders, order items and order payments, September 2016 to October 2018, in Brazilian real. Source: https://github.com/olist/work-at-olist-data. Check the dataset's licence and terms before reusing it. The raw files are not stored in this repo.

## Reproduce it

Python 3, standard library only.

```
python step1_data_quality_check.py            # downloads the 3 files into data/ and audits each table
python step2_three_way_reconciliation.py
python step2b_deep_dive_root_causes.py
python step3_build_exception_csvs.py          # writes the two CSV outputs
```

On the original files, step 3 gives the two committed CSVs exactly.

## Files

- `step1_data_quality_check.py`: downloads the data and checks each table on its own.
- `step2_three_way_reconciliation.py`: joins the three tables and compares billed and collected amounts.
- `step2b_deep_dive_root_causes.py`: traces the cause of the underpaid orders, the single-payment overcharges, the itemless active orders and the date defects.
- `step3_build_exception_csvs.py`: puts every order in exactly one bucket and writes the outputs.
- `reconciliation_queries.sql`: the same buckets in SQL (CTEs, joins, CASE), checked in SQLite against the Python counts.
- `reconciliation_summary_by_category.csv`: one row per bucket, covering all 99,441 orders.
- `reconciliation_exception_register.csv`: one row per flagged order.
