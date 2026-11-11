"""Static pin ownership checks. Firmware is parsed, never imported or executed."""

from .analyzer import Diagnostic, Report, analyze

__version__ = "0.1.0"
__all__ = ["Diagnostic", "Report", "analyze"]
