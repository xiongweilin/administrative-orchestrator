from __future__ import annotations

from .observability import install_observability
from .operations_api import app

install_observability(app, service_name="administrative-operations")

__all__ = ["app"]
