"""Length-matching helpers for regex batch KiCad signal path workflows."""

from __future__ import annotations

import copy
import math
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .types import SExp

DEFAULT_MATCH_TOLERANCE_MM = 0.01
DEFAULT_MATCH_MARGIN_MM = 0.5
DEFAULT_SNAKE_MAX_AMPLITUDE_MM = 0.5
EXISTING_SNAKE_MIN_SLACK_MM = 0.05
EXISTING_SNAKE_MIN_STEPS = 4
EXISTING_SNAKE_MIN_TURNS = 3
MATCH_RESULT_VERIFICATION_SLACK_MM = 5e-6
MATCH_MARGIN_SEARCH_STEP_MM = 0.01

__all__ = ["DEFAULT_MATCH_TOLERANCE_MM", "match_regex_measurements"]

if TYPE_CHECKING:
    from .core import BoardModel, Track


@dataclass(frozen=True)
class PathTrackStep:
    track: Track
    traversal_start_mm: tuple[float, float]
    traversal_end_mm: tuple[float, float]


@dataclass(frozen=True)
class MatchReplacementPlan:
    remove_indices: tuple[int, ...]
    insert_at: int
    replacement_nodes: tuple[list[SExp | str], ...]
    layer: str


@dataclass(frozen=True)
class RoutePrimitive:
    kind: str
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]
    mid_mm: tuple[float, float] | None = None


def _core():
    from . import core as core_module

    return core_module


def format_coord(value_mm: float) -> str:
    core_module = _core()
    normalized = 0.0 if core_module.is_zero(value_mm) else value_mm
    return f"{normalized:.6f}"


def serialize_atom(value: str) -> str:
    if value == "":
        return '""'
    if re.fullmatch(r'[^()\s"\\]+', value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def serialize_sexp(node: SExp, indent: int = 0) -> str:
    prefix = " " * indent
    if not isinstance(node, list):
        return prefix + serialize_atom(node)
    if not node:
        return prefix + "()"

    head_parts: list[str] = []
    child_index = 0
    while child_index < len(node) and not isinstance(node[child_index], list):
        head_parts.append(serialize_atom(node[child_index]))
        child_index += 1

    if child_index == len(node):
        return prefix + "(" + " ".join(head_parts) + ")"

    lines = [prefix + "(" + " ".join(head_parts)]
    for child in node[child_index:]:
        lines.append(serialize_sexp(child, indent + 2))
    lines.append(prefix + ")")
    return "\n".join(lines)


def serialize_kicad_value(value: str) -> str:
    if value == "":
        return '""'
    if re.fullmatch(r"[+-]?\d+(?:\.\d+)?", value):
        return value
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_+-]*", value):
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def serialize_kicad_child(node: list[SExp | str], indent: str) -> str:
    parts: list[str] = []
    for index, item in enumerate(node):
        if isinstance(item, list):
            raise ValueError("replacement segment nodes must remain one level deep")
        parts.append(item if index == 0 else serialize_kicad_value(item))
    return indent + "(" + " ".join(parts) + ")"


def set_child_atom_values(node: list[SExp | str], child_name: str, values: list[str]) -> None:
    for index, child in enumerate(node[1:], start=1):
        if isinstance(child, list) and child and child[0] == child_name:
            node[index] = [child_name, *values]
            return
    node.append([child_name, *values])


def refresh_uuid_fields(node: list[SExp | str]) -> None:
    core_module = _core()
    new_uuid = str(uuid.uuid4())
    for child_name in ("uuid", "tstamp"):
        child = core_module.first_child(node, child_name)
        if child is not None:
            child[:] = [child_name, new_uuid]


def point_along_segment(
    start: tuple[float, float],
    end: tuple[float, float],
    along_mm: float,
    offset_mm: float,
) -> tuple[float, float]:
    core_module = _core()
    length_mm = core_module.distance(start, end)
    if length_mm <= core_module.EPSILON:
        raise ValueError("cannot offset a zero-length segment")
    ux = (end[0] - start[0]) / length_mm
    uy = (end[1] - start[1]) / length_mm
    vx = -uy
    vy = ux
    return (
        start[0] + (ux * along_mm) + (vx * offset_mm),
        start[1] + (uy * along_mm) + (vy * offset_mm),
    )


def simplify_polyline(points: list[tuple[float, float]]) -> list[tuple[float, float]]:
    core_module = _core()
    simplified: list[tuple[float, float]] = []
    for point in points:
        if simplified and core_module.distance(simplified[-1], point) <= core_module.EPSILON:
            continue
        simplified.append(point)
    return simplified


def point_is_attachable(board: BoardModel, net_name: str, layer_name: str, point: tuple[float, float]) -> bool:
    for pad in board.pads:
        if pad.net != net_name:
            continue
        if pad.contains_point(point, layer_name, board.stackup):
            return True

    for via in board.vias:
        if via.net != net_name:
            continue
        if layer_name not in board.stackup.copper_span(via.layers[0], via.layers[-1]):
            continue
        if via.contains_point(point):
            return True

    return False


def escape_attach_margin(
    board: BoardModel,
    net_name: str,
    layer_name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    amplitude_mm: float,
    from_end: bool,
) -> float:
    core_module = _core()
    segment_length_mm = core_module.distance(start, end)
    along_mm = 0.0
    while along_mm <= (segment_length_mm / 2.0) + core_module.EPSILON:
        distance_from_start_mm = segment_length_mm - along_mm if from_end else along_mm
        base_point = point_along_segment(start, end, distance_from_start_mm, 0.0)
        offset_point = point_along_segment(start, end, distance_from_start_mm, amplitude_mm)
        if not point_is_attachable(board, net_name, layer_name, base_point) and not point_is_attachable(board, net_name, layer_name, offset_point):
            return min(along_mm + MATCH_MARGIN_SEARCH_STEP_MM, segment_length_mm / 2.0)
        along_mm += MATCH_MARGIN_SEARCH_STEP_MM
    raise ValueError(f"could not move the match detour outside the attach region for {net_name} on {layer_name}")


def build_route_template(node: list[SExp | str], kind: str) -> list[SExp | str]:
    template = copy.deepcopy(node)
    template[0] = kind
    filtered: list[SExp | str] = [template[0]]
    for child in template[1:]:
        if isinstance(child, list) and child and child[0] == "mid" and kind == "segment":
            continue
        filtered.append(child)
    return filtered


def build_smooth_tuned_primitives(
    board: BoardModel,
    net_name: str,
    layer_name: str,
    start: tuple[float, float],
    end: tuple[float, float],
    extra_length_mm: float,
) -> list[RoutePrimitive]:
    core_module = _core()
    segment_length_mm = core_module.distance(start, end)
    if segment_length_mm <= core_module.EPSILON:
        raise ValueError("cannot length-match using a zero-length segment")
    if extra_length_mm <= core_module.EPSILON:
        return [RoutePrimitive(kind="segment", start_mm=start, end_mm=end)]

    hump_count = max(1, int(math.ceil(extra_length_mm / ((math.pi - 2.0) * DEFAULT_SNAKE_MAX_AMPLITUDE_MM))))
    amplitude_mm = extra_length_mm / (hump_count * (math.pi - 2.0))
    radius_mm = amplitude_mm / 2.0
    required_width_mm = 4.0 * radius_mm * hump_count
    start_margin_mm = max(
        DEFAULT_MATCH_MARGIN_MM,
        escape_attach_margin(
            board,
            net_name,
            layer_name,
            start,
            end,
            amplitude_mm=amplitude_mm,
            from_end=False,
        ),
    )
    end_margin_mm = max(
        DEFAULT_MATCH_MARGIN_MM,
        escape_attach_margin(
            board,
            net_name,
            layer_name,
            start,
            end,
            amplitude_mm=amplitude_mm,
            from_end=True,
        ),
    )
    available_width_mm = segment_length_mm - start_margin_mm - end_margin_mm
    if available_width_mm + core_module.EPSILON < required_width_mm:
        raise ValueError(f"segment {net_name} on {layer_name} is too short to host a match detour")

    lead_slack_mm = (available_width_mm - required_width_mm) / 2.0
    primitives: list[RoutePrimitive] = []
    cursor_mm = start_margin_mm + lead_slack_mm

    def local_point(along_mm: float, offset_mm: float) -> tuple[float, float]:
        return point_along_segment(start, end, along_mm, offset_mm)

    if cursor_mm > core_module.EPSILON:
        primitives.append(RoutePrimitive(kind="segment", start_mm=start, end_mm=local_point(cursor_mm, 0.0)))

    for hump_index in range(hump_count):
        sign = 1.0 if hump_index % 2 == 0 else -1.0
        x0 = cursor_mm
        p0 = local_point(x0, 0.0)
        p1 = local_point(x0 + radius_mm, sign * radius_mm)
        p2 = local_point(x0 + 2.0 * radius_mm, sign * 2.0 * radius_mm)
        p3 = local_point(x0 + 3.0 * radius_mm, sign * radius_mm)
        p4 = local_point(x0 + 4.0 * radius_mm, 0.0)
        diag_mm = radius_mm / math.sqrt(2.0)
        m1 = local_point(x0 + diag_mm, sign * (radius_mm - diag_mm))
        m2 = local_point(x0 + 2.0 * radius_mm - diag_mm, sign * (radius_mm + diag_mm))
        m3 = local_point(x0 + 2.0 * radius_mm + diag_mm, sign * (radius_mm + diag_mm))
        m4 = local_point(x0 + 4.0 * radius_mm - diag_mm, sign * (radius_mm - diag_mm))

        primitives.extend(
            [
                RoutePrimitive("arc", p0, p1, m1),
                RoutePrimitive("arc", p1, p2, m2),
                RoutePrimitive("arc", p2, p3, m3),
                RoutePrimitive("arc", p3, p4, m4),
            ]
        )
        cursor_mm += 4.0 * radius_mm

    if segment_length_mm - cursor_mm > core_module.EPSILON:
        primitives.append(RoutePrimitive(kind="segment", start_mm=local_point(cursor_mm, 0.0), end_mm=end))

    return primitives


def build_replacement_nodes(
    template_node: list[SExp | str],
    primitives: list[RoutePrimitive],
) -> list[list[SExp | str]]:
    core_module = _core()
    replacements: list[list[SExp | str]] = []
    segment_template = build_route_template(template_node, "segment")
    arc_template = build_route_template(template_node, "arc")
    for primitive in primitives:
        if core_module.distance(primitive.start_mm, primitive.end_mm) <= core_module.EPSILON:
            continue
        node = copy.deepcopy(segment_template if primitive.kind == "segment" else arc_template)
        set_child_atom_values(node, "start", [format_coord(primitive.start_mm[0]), format_coord(primitive.start_mm[1])])
        set_child_atom_values(node, "end", [format_coord(primitive.end_mm[0]), format_coord(primitive.end_mm[1])])
        if primitive.kind == "arc":
            if primitive.mid_mm is None:
                raise ValueError("arc primitive requires a midpoint")
            set_child_atom_values(node, "mid", [format_coord(primitive.mid_mm[0]), format_coord(primitive.mid_mm[1])])
        refresh_uuid_fields(node)
        replacements.append(node)
    if not replacements:
        raise ValueError("length matching did not produce any routed segments")
    return replacements


def point_key(layer_name: str, net_name: str, point: tuple[float, float]) -> tuple[str, str, float, float]:
    return (layer_name, net_name, round(point[0], 6), round(point[1], 6))


def build_track_endpoint_usage(board: BoardModel) -> dict[tuple[str, str, float, float], set[int]]:
    usage: dict[tuple[str, str, float, float], set[int]] = {}
    for track in board.tracks:
        start_key = point_key(track.layer, track.net, track.start_mm)
        end_key = point_key(track.layer, track.net, track.end_mm)
        usage.setdefault(start_key, set()).add(track.source_index)
        usage.setdefault(end_key, set()).add(track.source_index)
    return usage


def build_path_track_sequence(board: BoardModel, result: dict[str, Any]) -> list[PathTrackStep | None]:
    path_edges = result["path_edges"]
    if not path_edges:
        return []

    tracks_by_index = {track.source_index: track for track in board.tracks}
    if len(path_edges) == 1:
        current_node = path_edges[0].a
    else:
        first_edge = path_edges[0]
        second_edge = path_edges[1]
        current_node = first_edge.b if first_edge.a in {second_edge.a, second_edge.b} else first_edge.a

    sequence: list[PathTrackStep | None] = []
    for edge in path_edges:
        if edge.a == current_node:
            next_node = edge.b
            traversed_forward = True
        elif edge.b == current_node:
            next_node = edge.a
            traversed_forward = False
        else:
            raise ValueError("could not orient the chosen path for matching")

        if edge.kind in {"segment", "arc"} and edge.board_item_index is not None:
            track = tracks_by_index.get(edge.board_item_index)
            if track is not None:
                start_mm = track.start_mm if traversed_forward else track.end_mm
                end_mm = track.end_mm if traversed_forward else track.start_mm
                sequence.append(
                    PathTrackStep(
                        track=track,
                        traversal_start_mm=start_mm,
                        traversal_end_mm=end_mm,
                    )
                )
            else:
                sequence.append(None)
        else:
            sequence.append(None)

        current_node = next_node

    return sequence


def internal_window_points_are_isolated(
    board: BoardModel,
    steps: list[PathTrackStep],
    endpoint_usage: dict[tuple[str, str, float, float], set[int]],
) -> bool:
    core_module = _core()
    for left_step, right_step in zip(steps, steps[1:]):
        if core_module.distance(left_step.traversal_end_mm, right_step.traversal_start_mm) > core_module.EPSILON:
            return False
        if point_is_attachable(board, left_step.track.net, left_step.track.layer, left_step.traversal_end_mm):
            return False
        expected_indices = {left_step.track.source_index, right_step.track.source_index}
        if endpoint_usage.get(point_key(left_step.track.layer, left_step.track.net, left_step.traversal_end_mm), set()) != expected_indices:
            return False
    return True


def window_turn_count(steps: list[PathTrackStep]) -> int:
    core_module = _core()
    previous_vector: tuple[float, float] | None = None
    turns = 0
    for step in steps:
        vector = (
            step.traversal_end_mm[0] - step.traversal_start_mm[0],
            step.traversal_end_mm[1] - step.traversal_start_mm[1],
        )
        vector_length_mm = core_module.distance(step.traversal_start_mm, step.traversal_end_mm)
        if vector_length_mm <= core_module.EPSILON:
            continue
        if previous_vector is not None:
            cross = abs(previous_vector[0] * vector[1] - previous_vector[1] * vector[0])
            if cross > core_module.EPSILON:
                turns += 1
        previous_vector = vector
    return turns


def is_existing_snake_window(
    steps: list[PathTrackStep],
    removable_slack_mm: float,
) -> bool:
    if len(steps) < EXISTING_SNAKE_MIN_STEPS:
        return False
    if removable_slack_mm < EXISTING_SNAKE_MIN_SLACK_MM:
        return False
    return window_turn_count(steps) >= EXISTING_SNAKE_MIN_TURNS


def child_point_mm(node: list[SExp | str], child_name: str) -> tuple[float, float] | None:
    core_module = _core()
    child = core_module.first_child(node, child_name)
    if child is None:
        return None
    x_value = core_module.float_atom(child, 1)
    y_value = core_module.float_atom(child, 2)
    if x_value is None or y_value is None:
        return None
    return (x_value, y_value)


def coordinate_key(point_mm: tuple[float, float]) -> tuple[float, float]:
    return (round(point_mm[0], 6), round(point_mm[1], 6))


def resolve_window_axis(steps: list[PathTrackStep]) -> tuple[tuple[float, float], tuple[float, float], tuple[float, float]]:
    core_module = _core()
    start_mm = steps[0].traversal_start_mm
    end_mm = steps[-1].traversal_end_mm
    axis_length_mm = core_module.distance(start_mm, end_mm)
    if axis_length_mm <= core_module.EPSILON:
        for step in steps:
            axis_length_mm = core_module.distance(step.traversal_start_mm, step.traversal_end_mm)
            if axis_length_mm > core_module.EPSILON:
                start_mm = step.traversal_start_mm
                end_mm = step.traversal_end_mm
                break
    if axis_length_mm <= core_module.EPSILON:
        raise ValueError("could not determine a stable axis for the existing snake window")
    ux = (end_mm[0] - start_mm[0]) / axis_length_mm
    uy = (end_mm[1] - start_mm[1]) / axis_length_mm
    vx = -uy
    vy = ux
    return start_mm, (ux, uy), (vx, vy)


def build_existing_snake_replacement(
    root: list[SExp | str],
    steps: list[PathTrackStep],
    length_delta_mm: float,
) -> MatchReplacementPlan:
    core_module = _core()
    if length_delta_mm <= core_module.EPSILON:
        raise ValueError("existing snake retuning only supports added length")

    start_mm, axis_u, axis_v = resolve_window_axis(steps)
    boundary_keys = {
        coordinate_key(steps[0].traversal_start_mm),
        coordinate_key(steps[-1].traversal_end_mm),
    }
    original_window_length_mm = sum(step.track.length_mm for step in steps)

    original_nodes: list[list[SExp | str]] = []
    point_coordinates: dict[tuple[float, float], tuple[float, float]] = {}
    projected_points: dict[tuple[float, float], tuple[float, float]] = {}
    lateral_values: list[float] = []

    for step in steps:
        node = root[step.track.source_index]
        if not isinstance(node, list):
            raise ValueError("could not load existing snake nodes for retuning")
        original_nodes.append(node)
        for child_name in ("start", "mid", "end"):
            point_mm = child_point_mm(node, child_name)
            if point_mm is None:
                continue
            key = coordinate_key(point_mm)
            point_coordinates.setdefault(key, point_mm)
            if key in projected_points:
                continue
            dx = point_mm[0] - start_mm[0]
            dy = point_mm[1] - start_mm[1]
            along_mm = (dx * axis_u[0]) + (dy * axis_u[1])
            lateral_mm = (dx * axis_v[0]) + (dy * axis_v[1])
            projected_points[key] = (along_mm, lateral_mm)
            if key not in boundary_keys:
                lateral_values.append(lateral_mm)

    if not lateral_values:
        raise ValueError("existing snake window does not expose any retunable interior points")

    lateral_min_mm = min(lateral_values)
    lateral_max_mm = max(lateral_values)
    if abs(lateral_max_mm - lateral_min_mm) <= core_module.EPSILON:
        raise ValueError("existing snake window does not have lateral spread to retune")
    lateral_center_mm = (lateral_min_mm + lateral_max_mm) / 2.0

    def transformed_points(scale: float) -> dict[tuple[float, float], tuple[float, float]]:
        mapping: dict[tuple[float, float], tuple[float, float]] = {}
        for key, point_mm in point_coordinates.items():
            if key in boundary_keys:
                mapping[key] = point_mm
                continue
            along_mm, lateral_mm = projected_points[key]
            scaled_lateral_mm = lateral_center_mm + ((lateral_mm - lateral_center_mm) * scale)
            mapping[key] = (
                start_mm[0] + (axis_u[0] * along_mm) + (axis_v[0] * scaled_lateral_mm),
                start_mm[1] + (axis_u[1] * along_mm) + (axis_v[1] * scaled_lateral_mm),
            )
        return mapping

    def render_scaled_nodes(scale: float) -> tuple[list[list[SExp | str]], float]:
        mapping = transformed_points(scale)
        updated_nodes: list[list[SExp | str]] = []
        updated_length_mm = 0.0
        for node in original_nodes:
            copied_node = copy.deepcopy(node)
            start_point_mm = child_point_mm(node, "start")
            end_point_mm = child_point_mm(node, "end")
            mid_point_mm = child_point_mm(node, "mid")
            if start_point_mm is None or end_point_mm is None:
                raise ValueError("existing snake node is missing endpoints")
            scaled_start_mm = mapping[coordinate_key(start_point_mm)]
            scaled_end_mm = mapping[coordinate_key(end_point_mm)]
            set_child_atom_values(copied_node, "start", [format_coord(scaled_start_mm[0]), format_coord(scaled_start_mm[1])])
            set_child_atom_values(copied_node, "end", [format_coord(scaled_end_mm[0]), format_coord(scaled_end_mm[1])])
            if mid_point_mm is not None:
                scaled_mid_mm = mapping[coordinate_key(mid_point_mm)]
                set_child_atom_values(copied_node, "mid", [format_coord(scaled_mid_mm[0]), format_coord(scaled_mid_mm[1])])
                updated_length_mm += core_module.arc_length(scaled_start_mm, scaled_mid_mm, scaled_end_mm)
            else:
                updated_length_mm += core_module.distance(scaled_start_mm, scaled_end_mm)
            refresh_uuid_fields(copied_node)
            updated_nodes.append(copied_node)
        return updated_nodes, updated_length_mm

    lower_scale = 1.0
    upper_scale = 1.0
    updated_nodes: list[list[SExp | str]] | None = None
    updated_length_mm = original_window_length_mm
    for _ in range(24):
        upper_scale *= 1.5
        updated_nodes, updated_length_mm = render_scaled_nodes(upper_scale)
        if updated_length_mm - original_window_length_mm + core_module.EPSILON >= length_delta_mm:
            break
    else:
        raise ValueError("existing snake window could not absorb the requested added length")

    for _ in range(40):
        candidate_scale = (lower_scale + upper_scale) / 2.0
        candidate_nodes, candidate_length_mm = render_scaled_nodes(candidate_scale)
        if candidate_length_mm - original_window_length_mm >= length_delta_mm:
            upper_scale = candidate_scale
            updated_nodes = candidate_nodes
            updated_length_mm = candidate_length_mm
        else:
            lower_scale = candidate_scale

    if updated_nodes is None or updated_length_mm - original_window_length_mm + core_module.EPSILON < length_delta_mm:
        raise ValueError("existing snake retuning did not reach the requested added length")

    remove_indices = tuple(step.track.source_index for step in steps)
    return MatchReplacementPlan(
        remove_indices=remove_indices,
        insert_at=min(remove_indices),
        replacement_nodes=tuple(updated_nodes),
        layer=steps[0].track.layer,
    )


def build_window_replacement(
    root: list[SExp | str],
    board: BoardModel,
    steps: list[PathTrackStep],
    length_delta_mm: float,
) -> MatchReplacementPlan:
    core_module = _core()
    first_step = steps[0]
    last_step = steps[-1]
    start_mm = first_step.traversal_start_mm
    end_mm = last_step.traversal_end_mm
    original_window_length_mm = sum(step.track.length_mm for step in steps)
    direct_length_mm = core_module.distance(start_mm, end_mm)
    desired_window_length_mm = original_window_length_mm + length_delta_mm
    required_detour_mm = desired_window_length_mm - direct_length_mm
    if required_detour_mm < -core_module.EPSILON:
        raise ValueError("route window does not have enough removable slack for the requested match target")

    template_source_index = first_step.track.source_index
    template_node = root[template_source_index]
    if not isinstance(template_node, list):
        raise ValueError("could not load a segment template for length matching")

    primitives = build_smooth_tuned_primitives(
        board,
        first_step.track.net,
        first_step.track.layer,
        start_mm,
        end_mm,
        required_detour_mm,
    )
    replacements = build_replacement_nodes(template_node, primitives)
    remove_indices = tuple(step.track.source_index for step in steps)
    return MatchReplacementPlan(
        remove_indices=remove_indices,
        insert_at=min(remove_indices),
        replacement_nodes=tuple(replacements),
        layer=first_step.track.layer,
    )


def choose_match_replacement(
    root: list[SExp | str],
    board: BoardModel,
    result: dict[str, Any],
    length_delta_mm: float,
) -> tuple[MatchReplacementPlan, Track]:
    sequence = build_path_track_sequence(board, result)
    endpoint_usage = build_track_endpoint_usage(board)
    single_candidates: list[tuple[float, float, MatchReplacementPlan, Track]] = []
    existing_snake_candidates: list[tuple[float, int, int, float, MatchReplacementPlan, Track]] = []

    for item in sequence:
        if item is None:
            continue
        try:
            plan = build_window_replacement(root, board, [item], length_delta_mm)
        except ValueError:
            continue
        direct_length_mm = _core().distance(item.traversal_start_mm, item.traversal_end_mm)
        single_candidates.append((item.track.length_mm - direct_length_mm, item.track.length_mm, plan, item.track))

    multi_candidates: list[tuple[float, float, float, int, bool, int, MatchReplacementPlan, Track]] = []
    block: list[PathTrackStep] = []
    for item in [*sequence, None]:
        if (
            item is None
            or (block and (item.track.net != block[-1].track.net or item.track.layer != block[-1].track.layer))
        ):
            if len(block) >= 2:
                for start_index in range(len(block)):
                    for end_index in range(start_index + 1, len(block)):
                        window = block[start_index : end_index + 1]
                        if not internal_window_points_are_isolated(board, window, endpoint_usage):
                            continue
                        try:
                            plan = build_window_replacement(root, board, window, length_delta_mm)
                        except ValueError:
                            continue
                        original_length_mm = sum(step.track.length_mm for step in window)
                        direct_length_mm = _core().distance(window[0].traversal_start_mm, window[-1].traversal_end_mm)
                        removable_slack_mm = original_length_mm - direct_length_mm
                        if is_existing_snake_window(window, removable_slack_mm):
                            try:
                                existing_plan = build_existing_snake_replacement(root, window, length_delta_mm)
                            except ValueError:
                                existing_plan = None
                            if existing_plan is not None:
                                existing_snake_candidates.append(
                                    (
                                        original_length_mm,
                                        len(window),
                                        window_turn_count(window),
                                        removable_slack_mm,
                                        existing_plan,
                                        window[0].track,
                                    )
                                )
                        multi_candidates.append(
                            (
                                removable_slack_mm,
                                original_length_mm,
                                removable_slack_mm / max(original_length_mm, _core().EPSILON),
                                len(window),
                                is_existing_snake_window(window, removable_slack_mm),
                                window_turn_count(window),
                                plan,
                                window[0].track,
                            )
                        )
            block = []

        if item is not None:
            block.append(item)

    if existing_snake_candidates:
        _, _, _, _, plan, track = min(
            existing_snake_candidates,
            key=lambda item: (item[0], item[1], -item[2], -item[3]),
        )
        return plan, track

    if multi_candidates:
        existing_snake_candidates = [candidate for candidate in multi_candidates if candidate[4]]
        if existing_snake_candidates:
            _, _, _, _, _, _, plan, track = max(
                existing_snake_candidates,
                key=lambda item: (item[2], item[0], item[5], -item[1]),
            )
            return plan, track
    if single_candidates:
        _, _, plan, track = max(single_candidates, key=lambda item: (item[0], item[1]))
        return plan, track
    if multi_candidates:
        _, _, _, _, _, _, plan, track = max(multi_candidates, key=lambda item: (item[0], item[1], item[3]))
        return plan, track

    raise ValueError(
        f"could not find a usable route window to length-match {result['source_net']} -> {result['destination_net']}"
    )


def apply_match_plans(root: list[SExp | str], plans: list[MatchReplacementPlan]) -> list[SExp | str]:
    plans_by_insert = {plan.insert_at: plan for plan in plans}
    remove_indices = {index for plan in plans for index in plan.remove_indices}
    updated_root: list[SExp | str] = []
    for index, node in enumerate(root):
        plan = plans_by_insert.get(index)
        if plan is not None:
            updated_root.extend(plan.replacement_nodes)
        if index in remove_indices:
            continue
        updated_root.append(node)
    return updated_root


def find_root_head_end(text: str) -> int:
    if not text.startswith("("):
        raise ValueError("expected board text to start with '('")
    index = 1
    while index < len(text) and text[index].isspace():
        index += 1
    while index < len(text) and (not text[index].isspace()) and text[index] not in "()":
        index += 1
    return index


def find_top_level_child_spans(text: str) -> list[tuple[int, int]]:
    head_end = find_root_head_end(text)
    spans: list[tuple[int, int]] = []
    depth = 1
    in_string = False
    escape = False
    child_start: int | None = None

    for index in range(head_end, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
            continue
        if char == "(":
            if depth == 1:
                child_start = index
            depth += 1
            continue
        if char == ")":
            depth -= 1
            if depth == 1 and child_start is not None:
                spans.append((child_start, index + 1))
                child_start = None
            if depth == 0:
                break

    return spans


def detect_segment_indentation(chunk_text: str) -> tuple[str, str, str]:
    node_start = chunk_text.find("(")
    if node_start == -1:
        raise ValueError("expected a top-level node chunk")
    leading = chunk_text[:node_start]
    node_text = chunk_text[node_start:]
    lines = node_text.splitlines()
    first_line = lines[0]
    outer_indent = first_line[: len(first_line) - len(first_line.lstrip())]
    child_indent = outer_indent + "  "
    for line in lines[1:]:
        if not line.strip():
            continue
        child_indent = line[: len(line) - len(line.lstrip())]
        break
    return leading, outer_indent, child_indent


def render_replacement_chunk(
    nodes: tuple[list[SExp | str], ...],
    template_chunk_text: str,
) -> str:
    leading, outer_indent, child_indent = detect_segment_indentation(template_chunk_text)
    rendered: list[str] = []
    for node in nodes:
        if not isinstance(node, list) or not node or node[0] not in {"segment", "arc"}:
            raise ValueError("replacement nodes must be route expressions")
        lines = [outer_indent + f"({node[0]}"]
        for child in node[1:]:
            if not isinstance(child, list):
                raise ValueError("replacement route children must be list expressions")
            lines.append(serialize_kicad_child(child, child_indent))
        lines.append(outer_indent + ")")
        rendered.append(leading + "\n".join(lines))
    return "".join(rendered)


def render_matched_text(
    original_text: str,
    plans: list[MatchReplacementPlan],
) -> str:
    child_spans = find_top_level_child_spans(original_text)
    if len(child_spans) < max((max(plan.remove_indices) for plan in plans), default=0):
        raise ValueError("match plans reference child indices outside the board text")

    head_end = find_root_head_end(original_text)
    chunks: dict[int, str] = {}
    previous_end = head_end
    for index, (_, child_end) in enumerate(child_spans, start=1):
        chunks[index] = original_text[previous_end:child_end]
        previous_end = child_end
    suffix = original_text[previous_end:]

    remove_indices = {index for plan in plans for index in plan.remove_indices}
    insert_chunks = {
        plan.insert_at: render_replacement_chunk(plan.replacement_nodes, chunks[plan.insert_at])
        for plan in plans
    }

    output_parts = [original_text[:head_end]]
    for index in range(1, len(child_spans) + 1):
        if index in insert_chunks:
            output_parts.append(insert_chunks[index])
        if index in remove_indices:
            continue
        output_parts.append(chunks[index])
    output_parts.append(suffix)
    return "".join(output_parts)


def match_regex_measurements(
    board_path: Path,
    src_net_regex: str,
    dst_net_template: str,
    explicit_pass_through_refs: set[str],
    include_via_length: bool,
    allow_alternative_paths: bool,
    *,
    auto_pass_through: bool = True,
    tolerance_mm: float = DEFAULT_MATCH_TOLERANCE_MM,
    output_path: Path | None = None,
) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    core_module = _core()
    if tolerance_mm < 0:
        raise ValueError("match tolerance must be non-negative")

    original_text, root, board = core_module.load_board_document(board_path)
    results = core_module.resolve_regex_measurements(
        board=board,
        src_net_regex=src_net_regex,
        dst_net_template=dst_net_template,
        explicit_pass_through_refs=explicit_pass_through_refs,
        include_via_length=include_via_length,
        allow_alternative_paths=allow_alternative_paths,
        auto_pass_through=auto_pass_through,
    )

    failed_results = [result for result in results if result.get("status") == "ERROR"]
    if failed_results:
        raise ValueError("cannot run --match while batch measurements still contain ERROR rows")

    summary = core_module.summarize_results(results)
    successful_count = int(summary["successful_count"] or 0)
    if successful_count < 2:
        destination = output_path or board_path
        if output_path is not None and output_path != board_path:
            output_path.write_text(original_text, encoding="utf-8")
        return destination, results, []

    target_total_mm = summary["max_total_mm"]
    if target_total_mm is None:
        raise ValueError("could not determine a match target length")

    replacement_plans: list[MatchReplacementPlan] = []
    planned_indices: set[int] = set()
    changes: list[dict[str, Any]] = []
    for result in results:
        total_length_mm = result.get("total_length_mm")
        if total_length_mm is None:
            continue
        delta_mm = float(target_total_mm) - float(total_length_mm)
        if abs(delta_mm) <= tolerance_mm + core_module.EPSILON:
            continue
        plan, track = choose_match_replacement(root, board, result, delta_mm)
        if planned_indices.intersection(plan.remove_indices):
            raise ValueError("multiple matched paths resolved to overlapping route windows; aborting --match")
        planned_indices.update(plan.remove_indices)
        replacement_plans.append(plan)
        changes.append(
            {
                "source_net": result["source_net"],
                "destination_net": result["destination_net"],
                "length_adjustment_mm": delta_mm,
                "target_total_mm": float(target_total_mm),
                "matched_track_layer": track.layer,
            }
        )

    destination = output_path or board_path
    if not changes:
        if output_path is not None and output_path != board_path:
            output_path.write_text(original_text, encoding="utf-8")
        return destination, results, []

    matched_text = render_matched_text(original_text, replacement_plans)
    matched_board = core_module.load_board_from_text(matched_text)
    matched_results = core_module.resolve_regex_measurements(
        board=matched_board,
        src_net_regex=src_net_regex,
        dst_net_template=dst_net_template,
        explicit_pass_through_refs=explicit_pass_through_refs,
        include_via_length=include_via_length,
        allow_alternative_paths=allow_alternative_paths,
        auto_pass_through=auto_pass_through,
    )
    matched_errors = [result for result in matched_results if result.get("status") == "ERROR"]
    if matched_errors:
        raise ValueError("length matching produced an invalid board state")

    matched_summary = core_module.summarize_results(matched_results)
    max_diff_mm = matched_summary["max_diff_mm"]
    if max_diff_mm is not None and max_diff_mm > tolerance_mm + MATCH_RESULT_VERIFICATION_SLACK_MM:
        raise ValueError(
            f"length matching reached max diff {core_module.format_length(float(max_diff_mm))}, "
            f"which exceeds tolerance {core_module.format_length(tolerance_mm)}"
        )

    destination.write_text(matched_text, encoding="utf-8")
    return destination, matched_results, changes
