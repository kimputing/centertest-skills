#!/bin/bash
# PostgreSQL query helper for CenterTest database
# Usage: ./query.sh "<SQL_QUERY>" [options]
#   Options:
#     -x    Expanded output (vertical format)
#     -c    CSV output
#     -t    Show timing

# Standard PostgreSQL environment variables win; the defaults are the local CenterTest dev database.
HOST="${PGHOST:-localhost}"
PORT="${PGPORT:-5432}"
DATABASE="${PGDATABASE:-centertest}"
DB_USER="${PGUSER:-centertest}"
PASSWORD="${PGPASSWORD:-centertest}"

QUERY="$1"
shift

EXTRA_OPTS=""
while getopts "xct" opt; do
  case $opt in
    x) EXTRA_OPTS="$EXTRA_OPTS -x" ;;
    c) EXTRA_OPTS="$EXTRA_OPTS -A -F','" ;;
    t) EXTRA_OPTS="$EXTRA_OPTS -c '\\timing on'" ;;
  esac
done

if [ -z "$QUERY" ]; then
  echo "Usage: $0 '<SQL_QUERY>' [-x] [-c] [-t]"
  echo "  -x  Expanded output"
  echo "  -c  CSV output"
  echo "  -t  Show timing"
  exit 1
fi

PGPASSWORD="$PASSWORD" psql -h "$HOST" -p "$PORT" -U "$DB_USER" -d "$DATABASE" $EXTRA_OPTS -c "$QUERY"
