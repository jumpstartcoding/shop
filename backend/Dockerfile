# Lambda container image for the API.
#
# A plain Debian Python image plus the AWS Lambda runtime client, rather than the Amazon
# Linux Lambda base image, because WeasyPrint needs Pango and HarfBuzz and Debian ships
# current, well-tested builds of both. Built for x86_64 (GitHub's standard runners).
#
#   docker build -t shop-api backend
#
# The deploy workflow builds this, pushes it to ECR, and points the Lambda function at it.

FROM python:3.12-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.20 /uv /usr/local/bin/uv
ENV UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /build
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra lambda --no-install-project


FROM python:3.12-slim-bookworm

# Pango + HarfBuzz for WeasyPrint. Document fonts are bundled with the app; DejaVu is only
# a fallback for characters Barlow doesn't cover.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
 && rm -rf /var/lib/apt/lists/* \
 && fc-cache -f

# Lambda's filesystem is read-only except /tmp; send caches there.
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache

COPY --from=build /opt/venv /opt/venv
WORKDIR /var/task
COPY alembic.ini ./
COPY migrations ./migrations
COPY app ./app
RUN python -m compileall -q app migrations

ENTRYPOINT ["python", "-m", "awslambdaric"]
CMD ["app.lambda_handler.handler"]
