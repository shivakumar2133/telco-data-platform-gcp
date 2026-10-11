#!/usr/bin/env bash
# Add the settings Airflow needs to .env (only the ones that are missing).
# Random secrets are generated locally; nothing is printed except the admin password.
set -euo pipefail
cd "$(dirname "$0")/.."
touch .env

add() {  # add KEY=VALUE if KEY is not already in .env
  local key="$1" value="$2"
  if ! grep -q "^${key}=" .env; then
    echo "${key}=${value}" >> .env
    echo "added   ${key}"
  else
    echo "exists  ${key}"
  fi
}

rand() { python3 -c "import secrets; print(secrets.token_urlsafe($1))"; }
fernet() { python3 -c "import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }

add AIRFLOW_UID "$(id -u)"                # files written by Airflow belong to you
add AIRFLOW_FERNET_KEY "$(fernet)"        # encrypts connections/variables in the Airflow DB
add AIRFLOW_JWT_SECRET "$(rand 32)"       # signs tokens between Airflow components
add AIRFLOW_ADMIN_PASSWORD "$(rand 12)"   # UI login for user 'admin'
add ALERT_WEBHOOK_URL ""                  # optional: Slack / Discord / Google Chat webhook

echo
echo "Airflow UI login -> user: admin   password: $(grep '^AIRFLOW_ADMIN_PASSWORD=' .env | cut -d= -f2-)"
