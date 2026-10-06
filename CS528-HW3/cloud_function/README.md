# HW3 HTTP Cloud Function

The Python entry point is [`get_file` in `main.py`](main.py), deployed as a Gen 2 cloud function with Python 3.12. It serves files from the HW2 bucket, filters the assignment's forbidden countries, publishes Pub/Sub events, and produces plain-text and structured error logs.

See the [HW3 project README](../README.md) for resource configuration, IAM permissions, deployment, the Mac subscriber, and verification commands. Deployment commands in that guide run from the `CS528-HW3/` directory.

CONNECT and TRACE return platform-generated 405 responses at the public Cloud Run endpoint before reaching this function. The application retains its generic 501 branch for non-GET/POST requests. The full explanation and the distinction between cloud and local tests are in the [platform limitation section](../README.md#connect-and-trace).
