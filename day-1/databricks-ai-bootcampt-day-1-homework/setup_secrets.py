"""One-time helper to store the Lakebase connection URL as a Databricks secret.

Run this once (from a terminal with Databricks auth configured, or a notebook)
after provisioning your Lakebase instance and creating a native-password role.
The deployed app reads the secret at runtime — no credentials are ever committed.

    python setup_secrets.py
"""

import getpass

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import workspace

w = WorkspaceClient()

SCOPE = "database"
KEY = "lakebase-url"

# create_scope errors if the scope already exists; ignore that case.
try:
    w.secrets.create_scope(scope=SCOPE)
    print(f"Created secret scope '{SCOPE}'.")
except Exception as e:
    print(f"Scope '{SCOPE}' already exists (or could not be created): {e}")

url = getpass.getpass(
    "Paste your Lakebase connection URL "
    "(postgresql://<role>:<password>@<host>.database.cloud.databricks.com:5432/"
    "databricks_postgres?sslmode=require): "
)
w.secrets.put_secret(scope=SCOPE, key=KEY, string_value=url)
print(f"Stored secret '{SCOPE}/{KEY}'.")

# Let the app's runtime identity read the secret.
w.secrets.put_acl(
    scope=SCOPE, principal="users", permission=workspace.AclPermission.READ
)
print("Granted READ to 'users'. Done.")
