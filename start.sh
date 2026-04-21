#!/bin/bash
set -e
echo "=== Python version ==="
python --version
echo "=== Testing imports ==="
python -c "import flask; print('flask ok')"
python -c "import flask_sqlalchemy; print('flask_sqlalchemy ok')"
python -c "import apscheduler; print('apscheduler ok')"
python -c "import psycopg2; print('psycopg2 ok')"
python -c "import pywebpush; print('pywebpush ok')" || echo "pywebpush FAILED (non-fatal)"
echo "=== Starting gunicorn ==="
exec gunicorn app:app --workers 1 --threads 2 --timeout 120 --bind 0.0.0.0:${PORT:-10000}
