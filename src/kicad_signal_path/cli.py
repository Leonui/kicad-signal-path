"""Console entrypoint for the installable KiCad signal path tool."""

from .core import build_arg_parser, main

__all__ = ["build_arg_parser", "main"]
