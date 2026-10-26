"""Submission configuration. The project is intentionally fixed for grading."""
PROJECT_ID = "dazzling-seat-508219-j3"
REGION = "us-central1"
ZONE = "us-central1-a"
BUCKET_NAME = "cs528-hw2-yf-2026"
PREFIX = "cs528-hw5"
SQL_INSTANCE = PREFIX + "-mysql"
DB_NAME = "hw5"
DB_USER = "hw5"
PASSWORD_SECRET = PREFIX + "-db-password"
INSTANCE_CONNECTION_NAME = f"{PROJECT_ID}:{REGION}:{SQL_INSTANCE}"
TOPIC_ID = PREFIX + "-forbidden"
SUBSCRIPTION_ID = TOPIC_ID + "-sub"
ARTIFACT_BUCKET = PROJECT_ID + "-hw5-deployment"
PORT = 8080
WEB_MACHINE = "e2-small"
REPORTER_MACHINE = "e2-micro"
SQL_TIER = "db-g1-small"
MARKER = "Managed by CS528 HW5 (Yide Fang)"
CLIENT_SHA256 = "10cb8c9f0fe29811c5201a25ba512e528d6e789ff576a94fd849d697ccb3a12a"


def service_account(role):
    return f"{PREFIX}-{role}@{PROJECT_ID}.iam.gserviceaccount.com"
