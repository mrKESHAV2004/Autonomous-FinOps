"""WSGI entry point: ``gunicorn 'finops_app.wsgi:app'``."""

from finops_app import create_app

app = create_app()
