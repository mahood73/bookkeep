#!/bin/bash

# Set DATABASE_URL explicitly to ensure it points to the correct location
export DATABASE_URL="${DATABASE_URL:-sqlite:////app/data/bookkeep.db}"

if [[ "$DATABASE_URL" == sqlite:* ]]; then
    # Ensure data directory exists (where SQLite DB will be created)
    mkdir -p /app/data
    chmod 755 /app/data
fi

# Set PYTHONPATH - Alembic needs to import app.* modules
export PYTHONPATH="/app/backend:$PYTHONPATH"

echo "Running database migrations..."

cd /app/backend

# Query the version table instead of looking for "(head)" in human-readable
# output. A tracked old revision is valid and must be upgraded, never stamped.
if ! LEGACY_REVISION=$(python -m app.migration_bootstrap); then
    echo "ERROR: Could not inspect database migration state."
    exit 1
fi
if [ -n "$LEGACY_REVISION" ]; then
    echo "Stamping legacy schema at revision $LEGACY_REVISION..."
    python -m alembic -c alembic.ini stamp "$LEGACY_REVISION" || exit 1
fi

# Run all pending migrations.  Fail loudly if something goes wrong so the
# problem is visible in container logs rather than silently masked.
echo "Applying pending Alembic migrations..."
if python -m alembic -c alembic.ini upgrade heads; then
    echo "Migrations completed successfully."
    python -m alembic -c alembic.ini current
else
    echo "ERROR: Alembic migrations failed. Check the logs above for details."
    exit 1
fi

# Start the application from /app (where uvicorn expects to find backend module)
cd /app
echo "Starting application..."
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port 8000
