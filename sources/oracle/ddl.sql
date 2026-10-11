-- Billing system (Oracle). Run as the BILLING schema owner.
-- Re-runnable: drops and recreates.
DROP TABLE IF EXISTS payments CASCADE CONSTRAINTS;
DROP TABLE IF EXISTS invoice_lines CASCADE CONSTRAINTS;
DROP TABLE IF EXISTS invoices CASCADE CONSTRAINTS;
DROP TABLE IF EXISTS billing_accounts CASCADE CONSTRAINTS;

CREATE TABLE billing_accounts (
  account_id        VARCHAR2(12)  PRIMARY KEY,
  customer_id       VARCHAR2(12)  NOT NULL,      -- CRM key, no FK (different system)
  billing_cycle_day NUMBER(2)     NOT NULL,
  payment_method    VARCHAR2(20)  NOT NULL,
  credit_class      VARCHAR2(1)   NOT NULL,
  created_at        TIMESTAMP(0)  NOT NULL,
  updated_at        TIMESTAMP(0)  NOT NULL
);

CREATE TABLE invoices (
  invoice_id    VARCHAR2(12)  PRIMARY KEY,
  account_id    VARCHAR2(12)  NOT NULL REFERENCES billing_accounts (account_id),
  invoice_date  DATE          NOT NULL,
  period_start  DATE          NOT NULL,
  period_end    DATE          NOT NULL,
  due_date      DATE          NOT NULL,
  total_amount  NUMBER(12,2)  NOT NULL,
  currency      VARCHAR2(3)   DEFAULT 'GBP' NOT NULL,
  status        VARCHAR2(20)  NOT NULL,
  created_at    TIMESTAMP(0)  NOT NULL,
  updated_at    TIMESTAMP(0)  NOT NULL
);

CREATE TABLE invoice_lines (
  line_id          VARCHAR2(14)   PRIMARY KEY,
  invoice_id       VARCHAR2(12)   NOT NULL REFERENCES invoices (invoice_id),
  subscription_id  VARCHAR2(12)   NOT NULL,     -- CRM key, no FK
  charge_type      VARCHAR2(20)   NOT NULL,
  description      VARCHAR2(200),
  quantity         NUMBER(10)     NOT NULL,
  amount           NUMBER(12,2)   NOT NULL
);

CREATE TABLE payments (
  payment_id      VARCHAR2(12)  PRIMARY KEY,
  invoice_id      VARCHAR2(12)  NOT NULL REFERENCES invoices (invoice_id),
  payment_date    DATE          NOT NULL,
  amount          NUMBER(12,2)  NOT NULL,
  payment_method  VARCHAR2(20)  NOT NULL,
  created_at      TIMESTAMP(0)  NOT NULL
);

-- Watermark indexes: incremental extraction (Phase 3) filters on these columns
CREATE INDEX ix_invoices_updated_at ON invoices (updated_at);
CREATE INDEX ix_accounts_updated_at ON billing_accounts (updated_at);
CREATE INDEX ix_payments_created_at ON payments (created_at);
CREATE INDEX ix_invoice_lines_invoice ON invoice_lines (invoice_id);
