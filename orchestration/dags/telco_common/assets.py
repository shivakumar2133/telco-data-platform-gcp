"""Data assets shared between DAGs (Airflow 3 data-aware scheduling).

A producer task lists an asset in `outlets`; a consumer DAG uses it as its
`schedule`. The consumer runs whenever the producer succeeds - no clock needed.
"""

from airflow.sdk import Asset

BRONZE_READY = Asset(name="bronze_ready", uri="telco://bronze/ready")
SILVER_READY = Asset(name="silver_ready", uri="telco://silver/ready")
