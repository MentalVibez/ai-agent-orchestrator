#!/bin/bash
# Docker entrypoint: run Alembic migrations then start the application.
# Uses 'set -e' so any migration error aborts startup (fail-fast).
# Uses 'exec' so uvicorn replaces this shell and receives PID 1 (proper signal handling).
set -e

echo "Running Alembic migrations..."
alembic upgrade head
echo "Migrations complete. Starting application..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
