"""Keyless authentication via service-account impersonation.

Your own login (Application Default Credentials) asks Google for a short-lived
token *as* a service account. No JSON key file ever exists, so none can leak.
Oracle analogy: a proxy user - CONNECT app_user[etl_owner] - you connect as
yourself but act with the target schema's privileges.

Requires roles/iam.serviceAccountTokenCreator on the SA (granted in iam.tf).
"""

from __future__ import annotations

import google.auth
from google.auth import impersonated_credentials

CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


def impersonate(sa_email: str, lifetime_s: int = 3600):
    """Return credentials that act as `sa_email`, or plain ADC if sa_email is empty."""
    source, _ = google.auth.default(scopes=[CLOUD_SCOPE])
    if not sa_email:
        return source
    return impersonated_credentials.Credentials(
        source_credentials=source,
        target_principal=sa_email,
        target_scopes=[CLOUD_SCOPE],
        lifetime=lifetime_s,
    )
