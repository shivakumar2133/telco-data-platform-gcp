// Power Query (M) for the Power BI model. Paste each query via
// Home -> Transform data -> New Source -> Blank Query -> Advanced Editor.
// First create a text parameter: Home -> Manage Parameters -> New: ProjectId = "telco-dp-..."
//
// BigQueryTable() navigates project -> dataset -> table with the native Google BigQuery
// connector, so filters "fold" into BigQuery SQL instead of downloading everything.

// ---- query: BigQueryTable   (a function; name it exactly BigQueryTable)
(dataset as text, table as text) as table =>
let
    Source = GoogleBigQuery.Database([BillingProject = ProjectId]),
    Project = Source{[Name = ProjectId]}[Data],
    Dataset = Project{[Name = dataset, Kind = "Schema"]}[Data],
    Result = Dataset{[Name = table, Kind = "Table"]}[Data]
in
    Result

// ---- query: kpi_monthly
let
    Source = BigQueryTable("gold", "rpt_kpi_monthly"),
    Typed = Table.TransformColumnTypes(Source, {
        {"month", type date},
        {"billed_revenue", Currency.Type}, {"billed_usage", Currency.Type},
        {"rated_usage", Currency.Type}, {"unbilled_usage", Currency.Type},
        {"leakage_subscriptions", Int64.Type}, {"call_attempts", Int64.Type},
        {"dropped_calls", Int64.Type}, {"voice_minutes", type number}, {"data_gb", type number},
        {"tickets", Int64.Type}, {"measured_tickets", Int64.Type}, {"breached_tickets", Int64.Type}})
in
    Typed

// ---- query: revenue_assurance
let
    Source = BigQueryTable("gold", "rpt_revenue_assurance"),
    Typed = Table.TransformColumnTypes(Source, {
        {"usage_month", type date}, {"subscriptions", Int64.Type}, {"cdr_count", Int64.Type},
        {"rated_amount", Currency.Type}, {"billed_amount", Currency.Type},
        {"variance_amount", Currency.Type}})
in
    Typed

// ---- query: network_daily
let
    Source = BigQueryTable("gold", "rpt_network_daily"),
    Typed = Table.TransformColumnTypes(Source, {
        {"call_date", type date}, {"date_key", Int64.Type}, {"active_cells", Int64.Type},
        {"call_attempts", Int64.Type}, {"voice_calls", Int64.Type}, {"dropped_calls", Int64.Type},
        {"failed_calls", Int64.Type}, {"voice_minutes", type number}, {"data_gb", type number}})
in
    Typed

// ---- query: sla_performance
let
    Source = BigQueryTable("gold", "rpt_sla_performance"),
    Typed = Table.TransformColumnTypes(Source, {
        {"opened_month", type date}, {"tickets", Int64.Type}, {"open_tickets", Int64.Type},
        {"closed_tickets", Int64.Type}, {"measured_tickets", Int64.Type},
        {"breached_tickets", Int64.Type}, {"total_resolution_hours", type number},
        {"tickets_missing_resolution_time", Int64.Type}, {"tickets_from_network_alarms", Int64.Type}})
in
    Typed

// ---- query: customer_base
let
    Source = BigQueryTable("gold", "rpt_customer_base"),
    Typed = Table.TransformColumnTypes(Source, {
        {"customers", Int64.Type}, {"customers_with_valid_email", Int64.Type},
        {"active_subscriptions", Int64.Type}})
in
    Typed

// ---- query: dim_date   (the date dimension from the star schema; no PII)
let
    Source = BigQueryTable("gold", "dim_date"),
    Typed = Table.TransformColumnTypes(Source, {
        {"date_key", Int64.Type}, {"date_day", type date}, {"month_start", type date}})
in
    Typed

// ---- query: dq_latest
let
    Source = BigQueryTable("ops", "rpt_dq_latest"),
    Typed = Table.TransformColumnTypes(Source, {
        {"population", Int64.Type}, {"failed_records", Int64.Type},
        {"failed_pct", type number}, {"max_failure_pct", type number}})
in
    Typed
