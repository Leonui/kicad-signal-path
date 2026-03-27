"""Type definitions for kicad-signal-path.

This module provides TypedDict definitions and type aliases for better type safety
throughout the codebase.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, TypeAlias

if TYPE_CHECKING:
    from typing import TypedDict
else:
    try:
        from typing import TypedDict
    except ImportError:
        from typing_extensions import TypedDict


# Type alias for S-expression recursive structure
SExp: TypeAlias = "list[SExp | str] | str"


class MeasurementResult(TypedDict):
    """Result of a single pad-to-pad measurement.

    Attributes:
        start_pad: Starting pad identifier (e.g., "U1:1")
        end_pad: Ending pad identifier (e.g., "J1:1")
        track_length_mm: Total length of track segments in millimeters
        via_length_mm: Total length of via vertical spans in millimeters
        total_length_mm: Combined track and via length in millimeters
        pass_through_refs: List of component references crossed (e.g., ["R1"])
        auto_pass_through_refs: Subset of pass_through_refs that were auto-detected
        nets_visited: List of net names traversed in order
        path_edges: List of Edge objects representing the path
        source_net: Starting net name
        destination_net: Ending net name
        status: "OK" for success, "ERROR" for failure
        error: Error message if status is "ERROR", None otherwise
    """
    start_pad: str
    end_pad: str
    track_length_mm: float | None
    via_length_mm: float | None
    total_length_mm: float | None
    pass_through_refs: list[str]
    auto_pass_through_refs: list[str]
    nets_visited: list[str]
    path_edges: list[object]  # List[Edge] but Edge is defined in core.py
    source_net: str | None
    destination_net: str | None
    status: str
    error: str | None


class SummaryMetrics(TypedDict):
    """Summary statistics for a batch of measurements.

    Attributes:
        successful_count: Number of successful measurements
        failed_count: Number of failed measurements
        min_total_mm: Minimum total length among successful measurements
        max_total_mm: Maximum total length among successful measurements
        max_diff_mm: Difference between max and min total lengths
    """
    successful_count: int
    failed_count: int
    min_total_mm: float | None
    max_total_mm: float | None
    max_diff_mm: float | None


class GraphEndpoints(TypedDict):
    """Graph node IDs for start and end pads.

    Attributes:
        start: Node ID for the starting pad
        end: Node ID for the ending pad
    """
    start: int
    end: int


__all__ = [
    "SExp",
    "MeasurementResult",
    "SummaryMetrics",
    "GraphEndpoints",
]
