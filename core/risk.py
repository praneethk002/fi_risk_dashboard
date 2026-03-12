"""
Bond risk metrics — re-exported from core.pricing.

This module exists for backwards-compatible imports. All implementations
live in core.pricing; see that module for full documentation.
"""

from core.pricing import (  # noqa: F401
    convexity,
    dv01,
    modified_duration,
)
