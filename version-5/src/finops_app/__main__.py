"""Development server: ``finops-web`` or ``python -m finops_app``.

Use a WSGI server in production, e.g. ``gunicorn 'finops_app.wsgi:app'``.
"""

from __future__ import annotations

import logging

from finops_app import create_app
from finops_app.config import Config

logger = logging.getLogger(__name__)


def main() -> None:
    config = Config.from_env()
    app = create_app(config)
    logger.info("FinOps Analyzer running on http://%s:%d", config.host, config.port)
    app.run(host=config.host, port=config.port, debug=config.debug)


if __name__ == "__main__":
    main()
