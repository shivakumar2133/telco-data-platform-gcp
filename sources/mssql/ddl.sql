-- CRM system (SQL Server), database "crm", schema dbo.
-- Re-runnable: drops and recreates.
DROP TABLE IF EXISTS dbo.subscriptions;
DROP TABLE IF EXISTS dbo.customers;
DROP TABLE IF EXISTS dbo.products;

CREATE TABLE dbo.products (
  product_id         VARCHAR(20)    NOT NULL PRIMARY KEY,
  product_name       NVARCHAR(100)  NOT NULL,
  product_type       VARCHAR(20)    NOT NULL,
  segment            VARCHAR(20)    NOT NULL,
  monthly_fee        DECIMAL(10,2)  NOT NULL,
  data_allowance_gb  INT            NULL,        -- NULL = unlimited
  minutes_allowance  INT            NULL,        -- NULL = unlimited
  sla_tier           VARCHAR(20)    NOT NULL,
  created_at         DATETIME2(0)   NOT NULL,
  updated_at         DATETIME2(0)   NOT NULL
);

CREATE TABLE dbo.customers (
  customer_id    VARCHAR(12)    NOT NULL PRIMARY KEY,
  segment        VARCHAR(20)    NOT NULL,
  first_name     NVARCHAR(100)  NULL,
  last_name      NVARCHAR(100)  NULL,
  company_name   NVARCHAR(200)  NULL,
  email          NVARCHAR(255)  NULL,
  msisdn         VARCHAR(15)    NULL,
  date_of_birth  DATE           NULL,
  address_line1  NVARCHAR(200)  NULL,
  city           NVARCHAR(100)  NULL,
  postcode       VARCHAR(10)    NULL,
  region         VARCHAR(50)    NULL,
  status         VARCHAR(20)    NOT NULL,
  created_at     DATETIME2(0)   NOT NULL,
  updated_at     DATETIME2(0)   NOT NULL
);

-- Legacy CRM: no FK from subscriptions to customers, so orphans can exist
CREATE TABLE dbo.subscriptions (
  subscription_id  VARCHAR(12)   NOT NULL PRIMARY KEY,
  customer_id      VARCHAR(12)   NOT NULL,
  product_id       VARCHAR(20)   NOT NULL REFERENCES dbo.products (product_id),
  msisdn           VARCHAR(15)   NULL,
  start_date       DATE          NOT NULL,
  end_date         DATE          NULL,
  status           VARCHAR(20)   NOT NULL,
  created_at       DATETIME2(0)  NOT NULL,
  updated_at       DATETIME2(0)  NOT NULL
);

CREATE INDEX ix_customers_updated_at ON dbo.customers (updated_at);
CREATE INDEX ix_subscriptions_updated_at ON dbo.subscriptions (updated_at);
