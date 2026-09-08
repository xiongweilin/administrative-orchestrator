FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml README.md alembic.ini ./
COPY alembic ./alembic
COPY src ./src

RUN pip install --no-cache-dir .

EXPOSE 8000 8010

CMD ["python", "-m", "uvicorn", "administrative_orchestrator.api:app", "--host", "0.0.0.0", "--port", "8000"]
