from __future__ import annotations

from .api import app
from .observability import install_observability

install_observability(app, service_name="administrative-api")

__all__ = ["app"]
