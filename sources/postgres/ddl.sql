-- Network inventory (PostgreSQL), database "network", schema public.
-- Re-runnable: drops and recreates.
DROP TABLE IF EXISTS devices;
DROP TABLE IF EXISTS cells;
DROP TABLE IF EXISTS sites;

CREATE TABLE sites (
  site_id     VARCHAR(10)   PRIMARY KEY,
  site_name   VARCHAR(120)  NOT NULL,
  site_type   VARCHAR(20)   NOT NULL,
  region      VARCHAR(50)   NOT NULL,
  postcode    VARCHAR(10),
  latitude    NUMERIC(8,5),
  longitude   NUMERIC(8,5),
  created_at  TIMESTAMP     NOT NULL,
  updated_at  TIMESTAMP     NOT NULL
);

CREATE TABLE cells (
  cell_id            VARCHAR(12)  PRIMARY KEY,
  site_id            VARCHAR(10)  NOT NULL REFERENCES sites (site_id),
  technology         VARCHAR(5)   NOT NULL,
  band               VARCHAR(5)   NOT NULL,
  sector             SMALLINT     NOT NULL,
  commissioned_date  DATE         NOT NULL,
  status             VARCHAR(20)  NOT NULL,
  updated_at         TIMESTAMP    NOT NULL
);

CREATE TABLE devices (
  device_id      VARCHAR(12)  PRIMARY KEY,
  site_id        VARCHAR(10)  NOT NULL REFERENCES sites (site_id),
  device_type    VARCHAR(20)  NOT NULL,
  vendor         VARCHAR(30)  NOT NULL,
  model          VARCHAR(50)  NOT NULL,
  serial_number  VARCHAR(20)  NOT NULL UNIQUE,
  install_date   DATE         NOT NULL,
  status         VARCHAR(20)  NOT NULL,
  updated_at     TIMESTAMP    NOT NULL
);

CREATE INDEX ix_sites_updated_at ON sites (updated_at);
CREATE INDEX ix_cells_updated_at ON cells (updated_at);
CREATE INDEX ix_devices_updated_at ON devices (updated_at);
