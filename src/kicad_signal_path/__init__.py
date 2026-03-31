"""Public package interface for the ``kicad-signal-path`` package."""

from importlib.metadata import PackageNotFoundError, version

from .core import (
    BoardParseError,
    build_arg_parser,
    format_length,
    load_board,
    main,
    measure,
    render_results_table,
    resolve_regex_measurements,
    summarize_results,
)
from .match import match_regex_measurements
from .types import MeasurementResult, SummaryMetrics
from .validation import ValidationError, ResourceLimitError, TimeoutError

__all__ = [
    "BoardParseError",
    "build_arg_parser",
    "format_length",
    "load_board",
    "match_regex_measurements",
    "main",
    "measure",
    "render_results_table",
    "resolve_regex_measurements",
    "summarize_results",
    "MeasurementResult",
    "SummaryMetrics",
    "ValidationError",
    "ResourceLimitError",
    "TimeoutError",
]

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version_tuple__ = ()
    try:
        __version__ = version("kicad-signal-path")
    except PackageNotFoundError:
        __version__ = "0+unknown"
