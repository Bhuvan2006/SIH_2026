#!/usr/bin/env bash
# Container entrypoint for a hosted deployment.
#
# The database is not in git: it is 170 MB once the 351k-product medicine
# catalogue is imported, far past GitHub's file limit. Rebuilding it on the
# host is not an option either -- that needs 147 MB of source CSVs, one of
# which is Kaggle-gated.
#
# So the built database ships as a gzipped GitHub Release asset and is fetched
# on first boot. Without it the app still starts, but on an empty database:
# price comparison and prescription brand matching would both be running
# against 45 curated drugs instead of 351,357 products, which looks like the
# features are broken rather than unseeded.
set -euo pipefail

DB_PATH="${DB_PATH:-/app/arogya.db}"

if [ ! -f "$DB_PATH" ]; then
  if [ -n "${DB_DOWNLOAD_URL:-}" ]; then
    echo "No database present. Fetching from DB_DOWNLOAD_URL..."
    curl -fsSL "$DB_DOWNLOAD_URL" -o /tmp/arogya.db.gz
    gunzip -c /tmp/arogya.db.gz > "$DB_PATH"
    rm -f /tmp/arogya.db.gz
    echo "Database restored: $(du -h "$DB_PATH" | cut -f1)"
  else
    echo "WARNING: no database and no DB_DOWNLOAD_URL set."
    echo "Starting on an empty database — the medicine catalogue will be missing."
  fi
fi

# Additive-only; safe on every boot, including when the database was just
# downloaded from a slightly older release.
python scripts/migrate_schema.py

# $PORT is set by Render, Railway and Fly. Default matches local development.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
