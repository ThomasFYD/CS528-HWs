"""Hourly authenticated function: stop this homework's running SQL instance."""
import os


def stop_database(request, session=None):
    if request.method != "POST":
        return {"error": "POST required"}, 405
    if session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession
        credentials, _ = google.auth.default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
        session = AuthorizedSession(credentials)
    project = os.environ["PROJECT_ID"]
    instance = os.environ["SQL_INSTANCE"]
    url = f"https://sqladmin.googleapis.com/sql/v1beta4/projects/{project}/instances/{instance}"
    current = session.get(url, timeout=30)
    current.raise_for_status()
    state = current.json()
    if state["settings"].get("activationPolicy") == "NEVER":
        return {"instance": instance, "action": "already_stopped"}, 200
    if state.get("state") != "RUNNABLE":
        # A maintenance/start/stop operation can be in progress. Scheduler retries.
        return {"instance": instance, "action": "retry", "state": state.get("state")}, 503
    response = session.patch(url, json={"settings": {"activationPolicy": "NEVER"}}, timeout=30)
    response.raise_for_status()
    return {"instance": instance, "action": "stop_requested",
            "operation": response.json().get("name")}, 200
