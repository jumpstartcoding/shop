"""AWS Lambda entry point.

HTTP requests (from the Function URL behind CloudFront) go to FastAPI through Mangum.
Operational tasks are direct invocations with a JSON payload:

    {"task": "migrate"}                                   run Alembic migrations to head
    {"task": "create_admin", "email": ..., "name": ...,   create the owner account
     "password": ...}
    {"task": "nightly"}                                   time-based upkeep (scheduled)
"""

from mangum import Mangum

from app.main import app

_http = Mangum(app, lifespan="off")


def handler(event, context):
    if isinstance(event, dict) and "task" in event:
        from app import tasks

        return tasks.run(event)
    return _http(event, context)
