# Matching engine evaluation

- **Engine version:** 1.0.0
- **Dataset:** generator 1.1.0, seed 42, profile full, content hash `32a2a5b2249fe8dd...`
- **Duplicate threshold:** 0.60 (tuned on seed 7)

## Targets (decision D3)

| Metric | Value | Target | Result |
|---|---|---|---|
| rule_precision | 1.000 | >= 0.99 | PASS |
| rule_recall | 1.000 | >= 0.99 | PASS |
| duplicate_recall | 1.000 | >= 0.95 | PASS |
| duplicate_precision | 1.000 | >= 0.85 | PASS |
| hard_negative_fp_rate | 0.000 | <= 0.01 | PASS |

## Per exception code

| Code | TP | FP | FN | Precision | Recall |
|---|---|---|---|---|---|
| BANK_DETAILS_CHANGED | 7 | 0 | 0 | 1.000 | 1.000 |
| CONTRACT_PRICE_DEVIATION | 51 | 0 | 0 | 1.000 | 1.000 |
| CURRENCY_MISMATCH | 17 | 0 | 0 | 1.000 | 1.000 |
| DUPLICATE_SUSPECTED | 52 | 0 | 0 | 1.000 | 1.000 |
| NO_GOODS_RECEIPT | 148 | 0 | 0 | 1.000 | 1.000 |
| NO_PO_REFERENCE | 102 | 0 | 0 | 1.000 | 1.000 |
| PAYMENT_TERMS_MISMATCH | 68 | 0 | 0 | 1.000 | 1.000 |
| PO_OVER_INVOICED | 17 | 0 | 0 | 1.000 | 1.000 |
| PRICE_VARIANCE | 385 | 0 | 0 | 1.000 | 1.000 |
| QTY_VARIANCE | 101 | 0 | 0 | 1.000 | 1.000 |

## Hard negatives (legitimate look-alikes)

0 of 1051 look-alike invoices received an exception (false-positive rate 0.00%).
