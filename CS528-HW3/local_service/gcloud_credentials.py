"""Refresh impersonated credentials using the user's existing gcloud session.

No service-account key file or Application Default Credentials login is used.
config-helper is an installed Cloud SDK helper; its token and actual expiry are
captured in memory, never printed or saved by this program.
"""

import json
import shutil
import subprocess
import threading
from datetime import datetime, timezone

from google.auth.credentials import Credentials
from google.auth.exceptions import RefreshError


class GcloudImpersonatedCredentials(Credentials):
    def __init__(self, account, service_account, project, gcloud="gcloud"):
        super().__init__()
        self.account = account
        self.service_account_email = service_account
        self.project = project
        self.gcloud = shutil.which(gcloud)
        if self.gcloud is None:
            raise RefreshError("gcloud was not found on PATH.")
        self._lock = threading.Lock()

    def refresh(self, request):
        del request  # Cloud SDK handles the IAM token exchange.
        with self._lock:
            command = [
                self.gcloud, "config", "config-helper", "--force-auth-refresh",
                f"--account={self.account}",
                f"--impersonate-service-account={self.service_account_email}",
                f"--project={self.project}", "--format=json", "--quiet",
            ]
            try:
                result = subprocess.run(
                    command, stdin=subprocess.DEVNULL, capture_output=True,
                    text=True, timeout=90, check=False,
                )
            except (OSError, subprocess.TimeoutExpired):
                raise RefreshError("Unable to run gcloud for impersonation.") from None
            if result.returncode:
                # Do not include command output, which may contain credentials.
                raise RefreshError(
                    "gcloud impersonation failed. Run 'gcloud auth login "
                    f"{self.account}' and check the Token Creator grant on "
                    f"{self.service_account_email}."
                )
            try:
                payload = json.loads(result.stdout)["credential"]
                token = payload["access_token"]
                expiry = datetime.fromisoformat(
                    payload["token_expiry"].replace("Z", "+00:00")
                )
                if not isinstance(token, str) or not token or expiry.tzinfo is None:
                    raise ValueError("Invalid token metadata")
                if expiry <= datetime.now(timezone.utc):
                    raise ValueError("Expired token")
            except (KeyError, ValueError, TypeError, AttributeError):
                raise RefreshError("gcloud returned invalid token metadata.") from None
            self.token = token
            # google-auth expects a naive datetime representing UTC.
            self.expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
