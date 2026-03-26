"""Public package interface for the ``kicad-signal-path`` package."""

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

__all__ = [
    "BoardParseError",
    "build_arg_parser",
    "format_length",
    "load_board",
    "main",
    "measure",
    "render_results_table",
    "resolve_regex_measurements",
    "summarize_results",
]

__version__ = "0.1.0"
