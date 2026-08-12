"""
One-time setup script: stores the Lakebase connection URL as a Databricks secret
Usage: python setup_secrets.py
"""

import getpass

from databricks.sdk import WorkspaceClient
from databricks.sdk.service import workspace


w = WorkspaceClient()

# w.secrets.create_scope(scope="database") # uncomment if the scope does not yet exist

w.secrets.put_secret(
    scope="database",
    key="lakebase-url",
    string_value=getpass.getpass("Paste your Lakebase URL: ")
)

w.secrets.put_acl(
    scope="database",
    principal="users",
    permission=workspace.AclPermission.READ,
)

print("Stored secret database/lakebase-url and grandted READ to users.")