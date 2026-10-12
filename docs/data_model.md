# Gold data model (star schema)

GitHub renders the diagram below. Every fact foreign key resolves to a dimension row;
unresolvable references point to the **Unknown member (`-1`)**, so facts are never dropped.

```mermaid
erDiagram
    dim_date ||--o{ fct_calls : date_key
    dim_customer ||--o{ fct_calls : "customer_sk (as of call time)"
    dim_product ||--o{ fct_calls : "product_sk (as of call time)"
    dim_subscription ||--o{ fct_calls : subscription_sk
    dim_cell ||--o{ fct_calls : cell_sk

    dim_customer ||--o{ fct_invoice_lines : "customer_sk (as of invoice date)"
    dim_product ||--o{ fct_invoice_lines : product_sk
    dim_subscription ||--o{ fct_invoice_lines : subscription_sk
    dim_customer ||--o{ fct_invoices : customer_sk

    dim_customer ||--o{ fct_tickets : "customer_sk (as of opened)"
    dim_sla ||--o{ fct_tickets : sla_sk
    dim_device ||--o{ fct_network_faults : device_sk

    dim_customer {
        int64 customer_sk PK "SCD2 version key"
        string customer_id "natural key"
        timestamp valid_from
        timestamp valid_to
        bool is_current
    }
    fct_calls {
        string cdr_id PK
        date call_date "partition"
        int64 cell_sk "cluster"
        int64 customer_sk "cluster"
        numeric charge_amount
        bool is_dropped
    }
    fct_invoice_lines {
        string line_id PK
        date period_month "partition (month)"
        string charge_type
        numeric amount
    }
```

## Facts

| Fact | Grain | Partition / cluster | Key measures |
|---|---|---|---|
| `fct_calls` | one call detail record | day of call / cell, customer | charge, duration, data, dropped |
| `fct_invoice_lines` | one invoice line | billing month / customer, charge type | amount |
| `fct_invoices` | one invoice | billing month / customer, status | total, lines total, paid, outstanding |
| `fct_tickets` | one trouble ticket | month opened / customer, priority | resolution hours vs SLA, breach |
| `fct_network_faults` | one network alarm | day raised / device, severity | duration, ticketed? |

## Dimensions

| Dimension | Type | Notes |
|---|---|---|
| `dim_customer` | SCD2 | from snapshot; first version valid from 1900-01-01 |
| `dim_product` | SCD2 | price history |
| `dim_subscription` | Type 1 | msisdn -> customer/product bridge; `is_orphan` flag |
| `dim_cell`, `dim_device` | Type 1 | denormalised with site (star, not snowflake) |
| `dim_sla` | Type 1 | targets per tier x priority |
| `dim_date` | static | 2018-2027, `date_key` = YYYYMMDD |

## Marts

| Mart | Purpose |
|---|---|
| `mart_revenue_assurance` | Rated usage vs billed usage per subscription per month: MATCHED / LEAKAGE / UNBILLED_NO_ACCOUNT / UNDER / OVER_BILLED |
| `mart_cell_daily` | Calls, drops, drop rate per cell per day (pre-aggregated for dashboards) |

## Reconciliation built into the model (dbt tests)
- `keys_match_source`: each fact has exactly one row per Silver key (no loss, no fan-out)
- `column_sum_matches`: money and counts in Gold equal Silver to the penny
- `scd2_valid_ranges`: versions have no gaps/overlaps and exactly one current row
- `relationships`: every fact key exists in its dimension
