"""AWS Lambda entry point.

HTTP requests (from the Function URL behind CloudFront) go to FastAPI through Mangum.
Operational tasks are direct invocations with a JSON payload:

    {"task": "migrate"}                                   run Alembic migrations to head
    {"task": "doctor"}                                    go-live checks (see app/doctor.py)
    {"task": "setup_shop"}                                placeholder profile + services list
    {"task": "create_admin", "email": ..., "name": ...,   create the owner account
     "password": ...}
    {"task": "nightly"}                                   time-based upkeep (scheduled)

Secrets are read from Parameter Store (SSM_PREFIX, e.g. /shop/prod) once per cold start,
before any settings are built.
"""

import os

if os.environ.get("SSM_PREFIX"):
    from app.core.ssm import load_parameters

    load_parameters(os.environ["SSM_PREFIX"])

from mangum import Mangum  # noqa: E402

from app.main import app  # noqa: E402

_http = Mangum(app, lifespan="off")


def handler(event, context):
    if isinstance(event, dict) and "task" in event:
        from app import tasks

        return tasks.run(event)
    return _http(event, context)
