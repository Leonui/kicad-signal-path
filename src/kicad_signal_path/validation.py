"""Input validation and resource limits for kicad-signal-path.

This module provides security and robustness checks to prevent:
- Stack overflow from deeply nested S-expressions
- Memory exhaustion from large files
- Infinite loops in pathfinding
- Malformed input causing crashes
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, TypeVar

# Security limits
MAX_FILE_SIZE_BYTES = 100 * 1024 * 1024  # 100 MB
MAX_RECURSION_DEPTH = 100  # Maximum nesting depth for S-expressions
MAX_PATHFINDING_TIME_SECONDS = 60.0  # Maximum time for pathfinding
MAX_GRAPH_NODES = 1_000_000  # Maximum nodes in routing graph
MAX_GRAPH_EDGES = 5_000_000  # Maximum edges in routing graph

# Supported KiCad file format versions
SUPPORTED_KICAD_VERSIONS = {"kicad_pcb"}  # Can be extended for version checking


class ValidationError(RuntimeError):
    """Raised when input validation fails."""
    pass


class ResourceLimitError(RuntimeError):
    """Raised when resource limits are exceeded."""
    pass


class TimeoutError(RuntimeError):
    """Raised when an operation exceeds its time limit."""
    pass


def validate_file_size(path: Path) -> None:
    """Check that file size is within acceptable limits.

    Args:
        path: Path to the file to validate

    Raises:
        ValidationError: If file is too large or doesn't exist
    """
    if not path.exists():
        raise ValidationError(f"File not found: {path}")

    if not path.is_file():
        raise ValidationError(f"Not a regular file: {path}")

    size = path.stat().st_size
    if size > MAX_FILE_SIZE_BYTES:
        size_mb = size / (1024 * 1024)
        limit_mb = MAX_FILE_SIZE_BYTES / (1024 * 1024)
        raise ValidationError(
            f"File too large: {size_mb:.1f} MB exceeds limit of {limit_mb:.1f} MB"
        )


def validate_recursion_depth(current_depth: int) -> None:
    """Check that recursion depth is within acceptable limits.

    Args:
        current_depth: Current recursion depth

    Raises:
        ResourceLimitError: If recursion depth exceeds limit
    """
    if current_depth > MAX_RECURSION_DEPTH:
        raise ResourceLimitError(
            f"Recursion depth {current_depth} exceeds limit of {MAX_RECURSION_DEPTH}. "
            f"File may be malformed or maliciously crafted."
        )


def validate_graph_size(node_count: int, edge_count: int) -> None:
    """Check that graph size is within acceptable limits.

    Args:
        node_count: Number of nodes in the graph
        edge_count: Number of edges in the graph

    Raises:
        ResourceLimitError: If graph size exceeds limits
    """
    if node_count > MAX_GRAPH_NODES:
        raise ResourceLimitError(
            f"Graph has {node_count:,} nodes, exceeds limit of {MAX_GRAPH_NODES:,}"
        )

    if edge_count > MAX_GRAPH_EDGES:
        raise ResourceLimitError(
            f"Graph has {edge_count:,} edges, exceeds limit of {MAX_GRAPH_EDGES:,}"
        )


T = TypeVar('T')


def with_timeout(func: Callable[..., T], timeout_seconds: float, *args: object, **kwargs: object) -> T:
    """Execute a function with a timeout.

    Args:
        func: Function to execute
        timeout_seconds: Maximum execution time in seconds
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        Result of func

    Raises:
        TimeoutError: If execution exceeds timeout
    """
    start_time = time.time()

    # For pathfinding, we need to check timeout periodically
    # This is a simple wrapper - actual timeout checking happens in the algorithm
    result = func(*args, **kwargs)

    elapsed = time.time() - start_time
    if elapsed > timeout_seconds:
        raise TimeoutError(
            f"Operation exceeded timeout of {timeout_seconds:.1f}s (took {elapsed:.1f}s)"
        )

    return result


class TimeoutChecker:
    """Helper class to check if an operation has exceeded its time limit.

    Usage:
        checker = TimeoutChecker(60.0)
        while processing:
            checker.check()  # Raises TimeoutError if exceeded
            # ... do work ...
    """

    def __init__(self, timeout_seconds: float) -> None:
        """Initialize timeout checker.

        Args:
            timeout_seconds: Maximum allowed execution time
        """
        self.timeout_seconds = timeout_seconds
        self.start_time = time.time()

    def check(self) -> None:
        """Check if timeout has been exceeded.

        Raises:
            TimeoutError: If execution time exceeds timeout
        """
        elapsed = time.time() - self.start_time
        if elapsed > self.timeout_seconds:
            raise TimeoutError(
                f"Operation exceeded timeout of {self.timeout_seconds:.1f}s "
                f"(elapsed: {elapsed:.1f}s)"
            )

    def elapsed(self) -> float:
        """Get elapsed time in seconds.

        Returns:
            Elapsed time since initialization
        """
        return time.time() - self.start_time


__all__ = [
    "MAX_FILE_SIZE_BYTES",
    "MAX_RECURSION_DEPTH",
    "MAX_PATHFINDING_TIME_SECONDS",
    "MAX_GRAPH_NODES",
    "MAX_GRAPH_EDGES",
    "ValidationError",
    "ResourceLimitError",
    "TimeoutError",
    "validate_file_size",
    "validate_recursion_depth",
    "validate_graph_size",
    "with_timeout",
    "TimeoutChecker",
]
