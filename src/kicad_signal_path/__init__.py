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

try:
    from ._version import __version__, __version_tuple__
except ImportError:
    __version_tuple__ = ()
    try:
        __version__ = version("kicad-signal-path")
    except PackageNotFoundError:
        __version__ = "0+unknown"
