"""Read secrets at runtime instead of from config files.

    get_secret("tickets-api-key")

Backends (env var SECRETS_BACKEND):
  gcp  (default)  Secret Manager, latest version
  env             environment variable with the name upper-cased, '-' -> '_'
                  e.g. tickets-api-key -> TICKETS_API_KEY. For unit tests and
                  fully offline work only.

Oracle analogy: Oracle Wallet - the program asks for a credential by alias
and never holds the password in its own source code.
"""

from __future__ import annotations

import os
from functools import lru_cache

from google.cloud import secretmanager


def env_name(secret_id: str) -> str:
    return secret_id.upper().replace("-", "_")


@lru_cache(maxsize=32)
def _from_gcp(project_id: str, secret_id: str, version: str, sa_email: str) -> str:
    from ingestion.common.gcp_auth import impersonate

    creds = impersonate(sa_email) if sa_email else None
    client = secretmanager.SecretManagerServiceClient(credentials=creds)
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version}"
    return client.access_secret_version(name=name).payload.data.decode("utf-8")


def get_secret(
    secret_id: str,
    project_id: str | None = None,
    version: str = "latest",
    sa_email: str = "",
) -> str:
    backend = os.getenv("SECRETS_BACKEND", "gcp").lower()
    if backend == "env":
        value = os.getenv(env_name(secret_id))
        if value is None:
            raise KeyError(f"SECRETS_BACKEND=env but {env_name(secret_id)} is not set")
        return value
    if backend != "gcp":
        raise ValueError(f"Unknown SECRETS_BACKEND {backend!r} (use 'gcp' or 'env')")

    project_id = project_id or os.getenv("GCP_PROJECT_ID")
    if not project_id:
        raise RuntimeError("GCP_PROJECT_ID is not set")
    return _from_gcp(project_id, secret_id, version, sa_email)
