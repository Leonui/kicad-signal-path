"""Measure exact pad-to-pad signal paths from KiCad PCB files.

This module contains the board parser, path solver, report helpers, and a
CLI-oriented entrypoint used by the installable ``kicad_signal_path`` package.
"""

from __future__ import annotations

import argparse
import heapq
import math
import re
import sys
from collections import defaultdict, deque
from dataclasses import dataclass
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Iterable


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


class BoardParseError(RuntimeError):
    pass


SExp = list["SExp | str"] | str
AUTO_PASS_THROUGH_REF_GLOBS = ("R*",)


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    i = 0
    length = len(text)
    while i < length:
        char = text[i]
        if char.isspace():
            i += 1
            continue
        if char == "(" or char == ")":
            tokens.append(char)
            i += 1
            continue
        if char == '"':
            i += 1
            parts: list[str] = []
            while i < length:
                char = text[i]
                if char == "\\":
                    i += 1
                    if i >= length:
                        raise BoardParseError("unterminated escape in quoted string")
                    parts.append(text[i])
                    i += 1
                    continue
                if char == '"':
                    i += 1
                    break
                parts.append(char)
                i += 1
            else:
                raise BoardParseError("unterminated quoted string")
            tokens.append("".join(parts))
            continue

        start = i
        while i < length and (not text[i].isspace()) and text[i] not in "()":
            i += 1
        tokens.append(text[start:i])
    return tokens


def parse_sexp(text: str) -> SExp:
    tokens = tokenize(text)
    index = 0

    def parse_expr() -> SExp:
        nonlocal index
        if index >= len(tokens):
            raise BoardParseError("unexpected end of file")
        token = tokens[index]
        index += 1
        if token == "(":
            result: list[SExp] = []
            while index < len(tokens) and tokens[index] != ")":
                result.append(parse_expr())
            if index >= len(tokens):
                raise BoardParseError("missing closing parenthesis")
            index += 1
            return result
        if token == ")":
            raise BoardParseError("unexpected closing parenthesis")
        return token

    parsed = parse_expr()
    if index != len(tokens):
        raise BoardParseError("trailing tokens after root expression")
    return parsed


def child_nodes(node: SExp, name: str) -> list[list[SExp | str]]:
    if not isinstance(node, list):
        return []
    return [child for child in node[1:] if isinstance(child, list) and child and child[0] == name]


def first_child(node: SExp, name: str) -> list[SExp | str] | None:
    matches = child_nodes(node, name)
    return matches[0] if matches else None


def atom(node: list[SExp | str] | None, index: int, default: str | None = None) -> str | None:
    if node is None or len(node) <= index:
        return default
    value = node[index]
    return value if isinstance(value, str) else default


def float_atom(node: list[SExp | str] | None, index: int, default: float | None = None) -> float | None:
    value = atom(node, index)
    if value is None:
        return default
    return float(value)


def rotate_clockwise(point: tuple[float, float], angle_deg: float) -> tuple[float, float]:
    angle_rad = math.radians(angle_deg)
    x, y = point
    cos_a = math.cos(angle_rad)
    sin_a = math.sin(angle_rad)
    return (x * cos_a + y * sin_a, -x * sin_a + y * cos_a)


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1])


def arc_length(start: tuple[float, float], mid: tuple[float, float], end: tuple[float, float]) -> float:
    ax, ay = start
    bx, by = mid
    cx, cy = end

    determinant = 2.0 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(determinant) < 1e-12:
        return distance(start, mid) + distance(mid, end)

    a_sq = ax * ax + ay * ay
    b_sq = bx * bx + by * by
    c_sq = cx * cx + cy * cy

    ux = (a_sq * (by - cy) + b_sq * (cy - ay) + c_sq * (ay - by)) / determinant
    uy = (a_sq * (cx - bx) + b_sq * (ax - cx) + c_sq * (bx - ax)) / determinant
    radius = math.hypot(ax - ux, ay - uy)
    if radius == 0:
        return 0.0

    start_angle = math.atan2(ay - uy, ax - ux)
    mid_angle = math.atan2(by - uy, bx - ux)
    end_angle = math.atan2(cy - uy, cx - ux)

    ccw_span = (end_angle - start_angle) % (2 * math.pi)
    mid_from_start = (mid_angle - start_angle) % (2 * math.pi)
    if mid_from_start <= ccw_span + 1e-12:
        span = ccw_span
    else:
        span = (2 * math.pi) - ccw_span
    return radius * span


def unique_sequence(values: Iterable[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


@dataclass(frozen=True)
class Stackup:
    copper_layers: tuple[str, ...]
    copper_z_mm: dict[str, float]

    @property
    def has_via_height_data(self) -> bool:
        return all(layer in self.copper_z_mm for layer in self.copper_layers)

    def via_length(self, start_layer: str, end_layer: str) -> float:
        if start_layer not in self.copper_z_mm or end_layer not in self.copper_z_mm:
            raise ValueError("board stackup does not define copper heights")
        return abs(self.copper_z_mm[end_layer] - self.copper_z_mm[start_layer])

    def copper_span(self, start_layer: str, end_layer: str) -> tuple[str, ...]:
        start_index = self.copper_layers.index(start_layer)
        end_index = self.copper_layers.index(end_layer)
        if start_index > end_index:
            start_index, end_index = end_index, start_index
        return self.copper_layers[start_index : end_index + 1]


@dataclass(frozen=True)
class Pad:
    ref: str
    footprint_uuid: str
    number: str
    pinfunction: str | None
    net: str | None
    kind: str
    shape: str
    center_mm: tuple[float, float]
    angle_deg: float
    size_mm: tuple[float, float]
    layers: tuple[str, ...]

    @property
    def identifier(self) -> str:
        return f"{self.ref}:{self.number}"

    @property
    def instance_key(self) -> tuple[str, str]:
        return (self.footprint_uuid, self.number)

    def copper_layers(self, stackup: Stackup) -> tuple[str, ...]:
        if "*.Cu" in self.layers:
            return stackup.copper_layers
        return tuple(layer for layer in self.layers if layer in stackup.copper_layers)

    def contains_point(self, point_mm: tuple[float, float], layer: str, stackup: Stackup, tolerance_mm: float = 0.02) -> bool:
        if layer not in self.copper_layers(stackup):
            return False

        px = point_mm[0] - self.center_mm[0]
        py = point_mm[1] - self.center_mm[1]
        local_x, local_y = rotate_clockwise((px, py), -self.angle_deg)
        width, height = self.size_mm
        half_w = width / 2.0 + tolerance_mm
        half_h = height / 2.0 + tolerance_mm

        if self.shape == "circle":
            radius = min(width, height) / 2.0 + tolerance_mm
            return (local_x * local_x + local_y * local_y) <= radius * radius

        if self.shape in {"rect", "roundrect", "trapezoid"}:
            return abs(local_x) <= half_w and abs(local_y) <= half_h

        if self.shape == "oval":
            if width >= height:
                straight = max((width - height) / 2.0, 0.0)
                if abs(local_x) <= straight:
                    return abs(local_y) <= half_h
                dx = abs(local_x) - straight
                radius = height / 2.0 + tolerance_mm
                return dx * dx + local_y * local_y <= radius * radius
            straight = max((height - width) / 2.0, 0.0)
            if abs(local_y) <= straight:
                return abs(local_x) <= half_w
            dy = abs(local_y) - straight
            radius = width / 2.0 + tolerance_mm
            return local_x * local_x + dy * dy <= radius * radius

        return abs(local_x) <= half_w and abs(local_y) <= half_h


@dataclass(frozen=True)
class Track:
    kind: str
    net: str
    layer: str
    start_mm: tuple[float, float]
    end_mm: tuple[float, float]
    mid_mm: tuple[float, float] | None
    length_mm: float


@dataclass(frozen=True)
class Via:
    net: str
    at_mm: tuple[float, float]
    layers: tuple[str, ...]


@dataclass(frozen=True)
class Edge:
    edge_id: int
    a: int
    b: int
    cost_mm: float
    track_mm: float
    via_mm: float
    kind: str
    net: str | None
    layer: str | None
    detail: str | None


@dataclass(frozen=True)
class BoardModel:
    stackup: Stackup
    nets_by_ordinal: dict[str, str]
    pads: tuple[Pad, ...]
    tracks: tuple[Track, ...]
    vias: tuple[Via, ...]


def group_pads_by_footprint(board: BoardModel) -> dict[str, list[Pad]]:
    grouped: dict[str, list[Pad]] = defaultdict(list)
    for pad in board.pads:
        grouped[pad.footprint_uuid].append(pad)
    return grouped


def build_footprint_ref_maps(board: BoardModel) -> tuple[dict[str, str], dict[str, set[str]]]:
    ref_by_uuid: dict[str, str] = {}
    uuids_by_ref: dict[str, set[str]] = defaultdict(set)
    for pad in board.pads:
        ref_by_uuid[pad.footprint_uuid] = pad.ref
        uuids_by_ref[pad.ref].add(pad.footprint_uuid)
    return ref_by_uuid, dict(uuids_by_ref)


def footprint_display_name(footprint_uuid: str, ref_by_uuid: dict[str, str], uuids_by_ref: dict[str, set[str]]) -> str:
    ref = ref_by_uuid[footprint_uuid]
    if len(uuids_by_ref[ref]) == 1:
        return ref
    return f"{ref}@{footprint_uuid[:8]}"


def pad_display_name(pad: Pad, ref_by_uuid: dict[str, str], uuids_by_ref: dict[str, set[str]]) -> str:
    return f"{footprint_display_name(pad.footprint_uuid, ref_by_uuid, uuids_by_ref)}:{pad.number}"


class DisjointSet:
    def __init__(self) -> None:
        self.parent: dict[int, int] = {}
        self.rank: dict[int, int] = {}

    def add(self, value: int) -> None:
        if value not in self.parent:
            self.parent[value] = value
            self.rank[value] = 0

    def find(self, value: int) -> int:
        parent = self.parent[value]
        if parent != value:
            self.parent[value] = self.find(parent)
        return self.parent[value]

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root == right_root:
            return
        left_rank = self.rank[left_root]
        right_rank = self.rank[right_root]
        if left_rank < right_rank:
            left_root, right_root = right_root, left_root
        self.parent[right_root] = left_root
        if left_rank == right_rank:
            self.rank[left_root] += 1


def parse_net_table(root: SExp) -> dict[str, str]:
    nets_by_ordinal: dict[str, str] = {}
    for node in child_nodes(root, "net"):
        ordinal = atom(node, 1)
        if ordinal is None or not ordinal.isdigit():
            continue
        nets_by_ordinal[ordinal] = atom(node, 2, "") or ""
    return nets_by_ordinal


def resolve_net_name(node: list[SExp | str] | None, nets_by_ordinal: dict[str, str]) -> str | None:
    ordinal = atom(node, 1)
    if ordinal is None:
        return None

    if not ordinal.isdigit():
        return ordinal or None

    inline_name = atom(node, 2)
    if inline_name is not None:
        known_name = nets_by_ordinal.get(ordinal)
        if known_name is not None and known_name != inline_name:
            raise BoardParseError(f"net ordinal '{ordinal}' maps to both '{known_name}' and '{inline_name}'")
        return inline_name or None

    if ordinal not in nets_by_ordinal:
        raise BoardParseError(f"net ordinal '{ordinal}' was referenced but not defined in the board net table")

    return nets_by_ordinal[ordinal] or None


def parse_board_copper_layers(root: SExp) -> tuple[str, ...]:
    layers_node = first_child(root, "layers")
    if layers_node is None:
        return ()

    copper_layers: list[str] = []
    for entry in layers_node[1:]:
        if not isinstance(entry, list):
            continue
        layer_name = atom(entry, 1)
        if layer_name and layer_name.endswith(".Cu"):
            copper_layers.append(layer_name)
    return tuple(copper_layers)


def parse_stackup(root: SExp, fallback_copper_layers: tuple[str, ...]) -> Stackup:
    setup = first_child(root, "setup")
    stackup_node = first_child(setup, "stackup") if setup else None
    if stackup_node is None:
        if not fallback_copper_layers:
            raise BoardParseError("board copper layers could not be determined")
        return Stackup(copper_layers=fallback_copper_layers, copper_z_mm={})

    copper_layers: list[str] = []
    copper_z_mm: dict[str, float] = {}
    z_mm = 0.0
    for layer_node in child_nodes(stackup_node, "layer"):
        layer_name = atom(layer_node, 1)
        if layer_name is None:
            continue
        if layer_name == "dielectric":
            dielectric_id = atom(layer_node, 2)
            if dielectric_id:
                layer_name = f"dielectric {dielectric_id}"
        layer_type = atom(first_child(layer_node, "type"), 1)
        thickness_mm = float_atom(first_child(layer_node, "thickness"), 1, 0.0) or 0.0
        if layer_type == "copper":
            copper_layers.append(layer_name)
            copper_z_mm[layer_name] = z_mm + (thickness_mm / 2.0)
            z_mm += thickness_mm
        else:
            z_mm += thickness_mm

    if not copper_layers:
        if not fallback_copper_layers:
            raise BoardParseError("no copper layers found in stackup")
        return Stackup(copper_layers=fallback_copper_layers, copper_z_mm={})

    return Stackup(copper_layers=tuple(copper_layers), copper_z_mm=copper_z_mm)


def parse_tracks(root: SExp, nets_by_ordinal: dict[str, str]) -> tuple[Track, ...]:
    result: list[Track] = []
    for kind in ("segment", "arc"):
        for node in child_nodes(root, kind):
            net = resolve_net_name(first_child(node, "net"), nets_by_ordinal)
            layer = atom(first_child(node, "layer"), 1)
            start_node = first_child(node, "start")
            end_node = first_child(node, "end")
            if not net or not layer or not start_node or not end_node:
                continue
            start = (float_atom(start_node, 1, 0.0) or 0.0, float_atom(start_node, 2, 0.0) or 0.0)
            end = (float_atom(end_node, 1, 0.0) or 0.0, float_atom(end_node, 2, 0.0) or 0.0)
            mid_node = first_child(node, "mid")
            mid = None
            if mid_node is not None:
                mid = (float_atom(mid_node, 1, 0.0) or 0.0, float_atom(mid_node, 2, 0.0) or 0.0)
            length_mm = distance(start, end) if kind == "segment" else arc_length(start, mid or start, end)
            result.append(
                Track(
                    kind=kind,
                    net=net,
                    layer=layer,
                    start_mm=start,
                    end_mm=end,
                    mid_mm=mid,
                    length_mm=length_mm,
                )
            )
    return tuple(result)


def parse_vias(root: SExp, nets_by_ordinal: dict[str, str]) -> tuple[Via, ...]:
    result: list[Via] = []
    for node in child_nodes(root, "via"):
        net = resolve_net_name(first_child(node, "net"), nets_by_ordinal)
        at_node = first_child(node, "at")
        layers_node = first_child(node, "layers")
        if not net or not at_node or layers_node is None or len(layers_node) < 3:
            continue
        at = (float_atom(at_node, 1, 0.0) or 0.0, float_atom(at_node, 2, 0.0) or 0.0)
        layers = tuple(value for value in layers_node[1:] if isinstance(value, str))
        result.append(Via(net=net, at_mm=at, layers=layers))
    return tuple(result)


def parse_pads(root: SExp, stackup: Stackup, nets_by_ordinal: dict[str, str]) -> tuple[Pad, ...]:
    result: list[Pad] = []
    for footprint in child_nodes(root, "footprint"):
        reference = None
        for prop in child_nodes(footprint, "property"):
            if atom(prop, 1) == "Reference":
                reference = atom(prop, 2)
                break
        if not reference:
            continue
        footprint_uuid = atom(first_child(footprint, "uuid"), 1)

        footprint_at = first_child(footprint, "at")
        if footprint_at is None:
            continue
        fp_x = float_atom(footprint_at, 1, 0.0) or 0.0
        fp_y = float_atom(footprint_at, 2, 0.0) or 0.0
        fp_angle = float_atom(footprint_at, 3, 0.0) or 0.0
        if not footprint_uuid:
            footprint_uuid = f"{reference}@{fp_x:.6f},{fp_y:.6f},{fp_angle:.3f}"

        for pad_node in child_nodes(footprint, "pad"):
            if len(pad_node) < 4:
                continue
            number = atom(pad_node, 1)
            kind = atom(pad_node, 2)
            shape = atom(pad_node, 3)
            at_node = first_child(pad_node, "at")
            size_node = first_child(pad_node, "size")
            layers_node = first_child(pad_node, "layers")
            if not number or not kind or not shape or at_node is None or size_node is None or layers_node is None:
                continue

            local_at = (float_atom(at_node, 1, 0.0) or 0.0, float_atom(at_node, 2, 0.0) or 0.0)
            local_angle = float_atom(at_node, 3, 0.0) or 0.0
            rotated_at = rotate_clockwise(local_at, fp_angle)
            center = (fp_x + rotated_at[0], fp_y + rotated_at[1])
            size = (float_atom(size_node, 1, 0.0) or 0.0, float_atom(size_node, 2, 0.0) or 0.0)
            layers = tuple(value for value in layers_node[1:] if isinstance(value, str))
            net = resolve_net_name(first_child(pad_node, "net"), nets_by_ordinal)
            pinfunction = atom(first_child(pad_node, "pinfunction"), 1)

            pad = Pad(
                ref=reference,
                footprint_uuid=footprint_uuid,
                number=number,
                pinfunction=pinfunction,
                net=net,
                kind=kind,
                shape=shape,
                center_mm=center,
                angle_deg=fp_angle + local_angle,
                size_mm=size,
                layers=layers,
            )
            if pad.copper_layers(stackup):
                result.append(pad)

    return tuple(result)


def load_board(path: Path) -> BoardModel:
    root = parse_sexp(path.read_text(encoding="utf-8"))
    if not isinstance(root, list) or not root or root[0] != "kicad_pcb":
        raise BoardParseError("root expression is not a kicad_pcb board")
    nets_by_ordinal = parse_net_table(root)
    copper_layers = parse_board_copper_layers(root)
    stackup = parse_stackup(root, copper_layers)
    return BoardModel(
        stackup=stackup,
        nets_by_ordinal=nets_by_ordinal,
        pads=parse_pads(root, stackup, nets_by_ordinal),
        tracks=parse_tracks(root, nets_by_ordinal),
        vias=parse_vias(root, nets_by_ordinal),
    )


def resolve_pad(board: BoardModel, selector: str) -> Pad:
    if ":" not in selector:
        raise ValueError(f"pad selector '{selector}' must look like REF:PAD")
    ref_selector, pad_number = selector.split(":", 1)
    footprint_uuid_prefix = None
    ref = ref_selector
    if "@" in ref_selector:
        ref, footprint_uuid_prefix = ref_selector.split("@", 1)

    matches = [
        pad
        for pad in board.pads
        if pad.ref == ref
        and pad.number == pad_number
        and (footprint_uuid_prefix is None or pad.footprint_uuid.startswith(footprint_uuid_prefix))
    ]
    if not matches:
        raise ValueError(f"pad '{selector}' was not found on the board")
    if len(matches) > 1:
        ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)
        candidate_names = ", ".join(sorted(pad_display_name(pad, ref_by_uuid, uuids_by_ref) for pad in matches))
        raise ValueError(f"pad selector '{selector}' matched multiple pads: {candidate_names}")
    return matches[0]


def compile_src_net_regex(pattern: str) -> tuple[re.Pattern[str], bool]:
    if len(pattern) >= 2 and pattern.startswith("/") and pattern.endswith("/"):
        return re.compile(f"^{pattern[:-1]}$"), True
    return re.compile(pattern), False


def expand_dst_template(template: str, match: re.Match[str], board_nets: set[str]) -> str:
    value = template
    value = re.sub(r"\(\$(\d+)\)", lambda token: match.group(int(token.group(1))) or "", value)
    value = re.sub(r"\$(\d+)", lambda token: match.group(int(token.group(1))) or "", value)
    if value not in board_nets and value.endswith("/") and value[:-1] in board_nets:
        value = value[:-1]
    return value


def find_bridge_footprints(board: BoardModel, left_net: str, right_net: str) -> set[str]:
    pads_by_footprint = group_pads_by_footprint(board)
    ref_by_uuid, _ = build_footprint_ref_maps(board)
    bridge_footprints: set[str] = set()
    for footprint_uuid, pads in pads_by_footprint.items():
        if len(pads) != 2:
            continue
        ref = ref_by_uuid.get(footprint_uuid)
        if ref is None or not any(fnmatchcase(ref, pattern) for pattern in AUTO_PASS_THROUGH_REF_GLOBS):
            continue
        pad_nets = {pad.net for pad in pads if pad.net}
        if pad_nets == {left_net, right_net}:
            bridge_footprints.add(footprint_uuid)
    return bridge_footprints


def nets_for_pass_through_footprints(board: BoardModel, footprint_uuids: set[str]) -> set[str]:
    pads_by_footprint = group_pads_by_footprint(board)
    nets: set[str] = set()
    for footprint_uuid in footprint_uuids:
        for pad in pads_by_footprint.get(footprint_uuid, []):
            if pad.net:
                nets.add(pad.net)
    return nets


def labels_for_footprints(board: BoardModel, footprint_uuids: set[str]) -> list[str]:
    ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)
    return [
        footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref)
        for footprint_uuid in sorted(footprint_uuids)
    ]


def select_pass_through_footprints(
    board: BoardModel,
    left_net: str | None,
    right_net: str | None,
    explicit_pass_through_footprints: set[str],
    auto_pass_through: bool,
) -> tuple[set[str], set[str]]:
    auto_pass_through_footprints: set[str] = set()
    if auto_pass_through and left_net and right_net:
        auto_pass_through_footprints = find_bridge_footprints(board, left_net, right_net) - explicit_pass_through_footprints
    all_pass_through_footprints = explicit_pass_through_footprints | auto_pass_through_footprints
    return all_pass_through_footprints, auto_pass_through_footprints


def resolve_pass_through_footprints(board: BoardModel, selectors: set[str]) -> set[str]:
    if not selectors:
        return set()

    pads_by_footprint = group_pads_by_footprint(board)
    ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)
    resolved: set[str] = set()

    for selector in selectors:
        if selector.startswith("uuid:"):
            uuid_prefix = selector[5:]
            matches = [footprint_uuid for footprint_uuid in pads_by_footprint if footprint_uuid.startswith(uuid_prefix)]
        elif "@" in selector:
            ref, uuid_prefix = selector.split("@", 1)
            matches = [
                footprint_uuid
                for footprint_uuid, footprint_ref in ref_by_uuid.items()
                if footprint_ref == ref and footprint_uuid.startswith(uuid_prefix)
            ]
        else:
            matches = sorted(uuids_by_ref.get(selector, set()))
            if len(matches) > 1:
                choices = ", ".join(footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref) for footprint_uuid in matches)
                raise ValueError(f"pass-through selector '{selector}' is ambiguous; use one of: {choices}")

        if not matches:
            raise ValueError(f"pass-through selector '{selector}' was not found")
        if len(matches) > 1:
            choices = ", ".join(footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref) for footprint_uuid in matches)
            raise ValueError(f"pass-through selector '{selector}' matched multiple footprints: {choices}")

        footprint_uuid = matches[0]
        if len(pads_by_footprint[footprint_uuid]) != 2:
            label = footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref)
            raise ValueError(f"pass-through selector '{selector}' resolved to '{label}', which does not have exactly 2 copper pads")
        resolved.add(footprint_uuid)

    return resolved


def resolve_unique_pad_for_net(board: BoardModel, net_name: str, excluded_footprints: set[str]) -> Pad:
    ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)
    candidates = [pad for pad in board.pads if pad.net == net_name and pad.footprint_uuid not in excluded_footprints]
    if not candidates:
        excluded = ""
        if excluded_footprints:
            labels = sorted(footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref) for footprint_uuid in excluded_footprints)
            excluded = f" after excluding {labels}"
        raise ValueError(f"no pad found on net '{net_name}'{excluded}")
    if len(candidates) > 1:
        candidate_names = ", ".join(sorted(pad_display_name(pad, ref_by_uuid, uuids_by_ref) for pad in candidates))
        raise ValueError(f"net '{net_name}' resolved to multiple possible endpoint pads: {candidate_names}")
    return candidates[0]


def resolve_regex_measurements(
    board: BoardModel,
    src_net_regex: str,
    dst_net_template: str,
    explicit_pass_through_refs: set[str],
    include_via_length: bool,
    allow_alternative_paths: bool,
    auto_pass_through: bool = True,
) -> list[dict[str, object]]:
    compiled, use_fullmatch = compile_src_net_regex(src_net_regex)
    board_nets = {pad.net for pad in board.pads if pad.net}
    ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)
    explicit_pass_through_footprints = resolve_pass_through_footprints(board, explicit_pass_through_refs)

    def match_net(net_name: str) -> re.Match[str] | None:
        if use_fullmatch:
            return compiled.fullmatch(net_name)
        return compiled.search(net_name)

    matched_source_nets = sorted({net for net in board_nets if net and match_net(net)})
    if not matched_source_nets:
        raise ValueError(f"source regex '{src_net_regex}' matched no nets")

    results: list[dict[str, object]] = []
    for source_net in matched_source_nets:
        match = match_net(source_net)
        if match is None:
            continue
        destination_net = expand_dst_template(dst_net_template, match, board_nets)
        if destination_net not in board_nets:
            raise ValueError(f"destination net '{destination_net}' derived from '{source_net}' was not found")

        pass_through_footprints, auto_pass_through_footprints = select_pass_through_footprints(
            board=board,
            left_net=source_net,
            right_net=destination_net,
            explicit_pass_through_footprints=explicit_pass_through_footprints,
            auto_pass_through=auto_pass_through,
        )
        pass_through_labels = labels_for_footprints(board, pass_through_footprints)
        auto_pass_through_labels = labels_for_footprints(board, auto_pass_through_footprints)

        try:
            start_pad = resolve_unique_pad_for_net(board, source_net, pass_through_footprints)
            end_pad = resolve_unique_pad_for_net(board, destination_net, pass_through_footprints)
            result = measure(
                board=board,
                start_selector=pad_display_name(start_pad, ref_by_uuid, uuids_by_ref),
                end_selector=pad_display_name(end_pad, ref_by_uuid, uuids_by_ref),
                allowed_pass_through_refs=explicit_pass_through_refs,
                auto_pass_through=auto_pass_through,
                include_via_length=include_via_length,
                allow_alternative_paths=allow_alternative_paths,
            )
            result["source_net"] = source_net
            result["destination_net"] = destination_net
            results.append(result)
        except ValueError as exc:
            start_label = "(unresolved)"
            end_label = "(unresolved)"
            try:
                start_pad = resolve_unique_pad_for_net(board, source_net, pass_through_footprints)
                start_label = pad_display_name(start_pad, ref_by_uuid, uuids_by_ref)
            except ValueError:
                pass
            try:
                end_pad = resolve_unique_pad_for_net(board, destination_net, pass_through_footprints)
                end_label = pad_display_name(end_pad, ref_by_uuid, uuids_by_ref)
            except ValueError:
                pass

            results.append(
                {
                    "start_pad": start_label,
                    "end_pad": end_label,
                    "track_length_mm": None,
                    "via_length_mm": None,
                    "total_length_mm": None,
                    "pass_through_refs": pass_through_labels,
                    "auto_pass_through_refs": auto_pass_through_labels,
                    "nets_visited": [],
                    "path_edges": [],
                    "source_net": source_net,
                    "destination_net": destination_net,
                    "status": "ERROR",
                    "error": str(exc),
                }
            )

    return results


def build_graph(
    board: BoardModel,
    start_pad: Pad,
    end_pad: Pad,
    allowed_pass_through_footprints: set[str],
    include_via_length: bool,
) -> tuple[dict[int, list[tuple[int, Edge]]], dict[int, tuple[object, ...]], list[Edge], dict[str, int]]:
    node_ids: dict[tuple[object, ...], int] = {}
    reverse_nodes: dict[int, tuple[object, ...]] = {}
    adjacency: dict[int, list[tuple[int, Edge]]] = defaultdict(list)
    edges: list[Edge] = []
    point_node_nets: dict[int, set[str]] = defaultdict(set)
    edge_counter = 0
    pads_by_footprint = group_pads_by_footprint(board)
    ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)

    def get_node(key: tuple[object, ...]) -> int:
        node_id = node_ids.get(key)
        if node_id is None:
            node_id = len(node_ids)
            node_ids[key] = node_id
            reverse_nodes[node_id] = key
        return node_id

    def add_edge(
        left: int,
        right: int,
        *,
        cost_mm: float,
        track_mm: float,
        via_mm: float,
        kind: str,
        net: str | None,
        layer: str | None,
        detail: str | None,
    ) -> None:
        nonlocal edge_counter
        edge = Edge(
            edge_id=edge_counter,
            a=left,
            b=right,
            cost_mm=cost_mm,
            track_mm=track_mm,
            via_mm=via_mm,
            kind=kind,
            net=net,
            layer=layer,
            detail=detail,
        )
        edge_counter += 1
        edges.append(edge)
        adjacency[left].append((right, edge))
        adjacency[right].append((left, edge))

    point_nodes_by_layer: dict[str, set[int]] = defaultdict(set)

    for track in board.tracks:
        start_node = get_node(("point", track.layer, round(track.start_mm[0], 6), round(track.start_mm[1], 6)))
        end_node = get_node(("point", track.layer, round(track.end_mm[0], 6), round(track.end_mm[1], 6)))
        point_node_nets[start_node].add(track.net)
        point_node_nets[end_node].add(track.net)
        point_nodes_by_layer[track.layer].add(start_node)
        point_nodes_by_layer[track.layer].add(end_node)
        add_edge(
            start_node,
            end_node,
            cost_mm=track.length_mm,
            track_mm=track.length_mm,
            via_mm=0.0,
            kind=track.kind,
            net=track.net,
            layer=track.layer,
            detail=None,
        )

    for via in board.vias:
        copper_span = board.stackup.copper_span(via.layers[0], via.layers[-1])
        via_nodes: list[int] = []
        for layer in copper_span:
            node = get_node(("point", layer, round(via.at_mm[0], 6), round(via.at_mm[1], 6)))
            point_node_nets[node].add(via.net)
            point_nodes_by_layer[layer].add(node)
            via_nodes.append(node)
        for left_layer, right_layer, left_node, right_node in zip(copper_span, copper_span[1:], via_nodes, via_nodes[1:]):
            raw_via_mm = 0.0
            if board.stackup.has_via_height_data:
                raw_via_mm = board.stackup.via_length(left_layer, right_layer)
            add_edge(
                left_node,
                right_node,
                cost_mm=raw_via_mm if include_via_length else 0.0,
                track_mm=0.0,
                via_mm=raw_via_mm,
                kind="via",
                net=via.net,
                layer=f"{left_layer}->{right_layer}",
                detail=None,
            )

    pad_anchor_nodes: dict[tuple[str, str], int] = {}
    for pad in board.pads:
        anchor_node = get_node(("pad", pad.footprint_uuid, pad.number))
        pad_anchor_nodes[pad.instance_key] = anchor_node
        for layer in pad.copper_layers(board.stackup):
            for point_node in point_nodes_by_layer.get(layer, set()):
                if pad.net and pad.net not in point_node_nets[point_node]:
                    continue
                point_key = reverse_nodes[point_node]
                point = (float(point_key[2]), float(point_key[3]))
                if pad.contains_point(point, layer, board.stackup):
                    add_edge(
                        anchor_node,
                        point_node,
                        cost_mm=0.0,
                        track_mm=0.0,
                        via_mm=0.0,
                        kind="pad",
                        net=pad.net,
                        layer=layer,
                        detail=pad_display_name(pad, ref_by_uuid, uuids_by_ref),
                    )

    for footprint_uuid in allowed_pass_through_footprints:
        footprint_pads = pads_by_footprint.get(footprint_uuid)
        if not footprint_pads:
            raise ValueError(f"pass-through footprint '{footprint_uuid}' was not found")
        if len(footprint_pads) != 2:
            label = footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref)
            raise ValueError(f"pass-through footprint '{label}' must have exactly 2 copper pads, found {len(footprint_pads)}")
        left_pad, right_pad = footprint_pads
        left_anchor = pad_anchor_nodes[left_pad.instance_key]
        right_anchor = pad_anchor_nodes[right_pad.instance_key]
        add_edge(
            left_anchor,
            right_anchor,
            cost_mm=0.0,
            track_mm=0.0,
            via_mm=0.0,
            kind="pass_through",
            net=None,
            layer=None,
            detail=footprint_display_name(footprint_uuid, ref_by_uuid, uuids_by_ref),
        )

    start_node = pad_anchor_nodes[start_pad.instance_key]
    end_node = pad_anchor_nodes[end_pad.instance_key]
    if start_node not in adjacency:
        raise ValueError(f"start pad '{pad_display_name(start_pad, ref_by_uuid, uuids_by_ref)}' has no routed copper touching it")
    if end_node not in adjacency:
        raise ValueError(f"end pad '{pad_display_name(end_pad, ref_by_uuid, uuids_by_ref)}' has no routed copper touching it")

    endpoint_nodes = {"start": start_node, "end": end_node}
    return adjacency, reverse_nodes, edges, endpoint_nodes


def shortest_path(
    adjacency: dict[int, list[tuple[int, Edge]]],
    start: int,
    end: int,
    banned_edge_ids: set[int] | None = None,
) -> tuple[float, list[Edge]]:
    banned_edge_ids = banned_edge_ids or set()
    queue: list[tuple[float, int]] = [(0.0, start)]
    distances: dict[int, float] = {start: 0.0}
    previous: dict[int, tuple[int, Edge]] = {}

    while queue:
        current_distance, node = heapq.heappop(queue)
        if current_distance > distances.get(node, math.inf) + 1e-12:
            continue
        if node == end:
            break
        for neighbor, edge in adjacency.get(node, []):
            if edge.edge_id in banned_edge_ids:
                continue
            next_distance = current_distance + edge.cost_mm
            if next_distance + 1e-12 < distances.get(neighbor, math.inf):
                distances[neighbor] = next_distance
                previous[neighbor] = (node, edge)
                heapq.heappush(queue, (next_distance, neighbor))

    if end not in distances:
        raise ValueError("no routed path was found between the selected pads")

    path_edges: list[Edge] = []
    cursor = end
    while cursor != start:
        prev_node, edge = previous[cursor]
        path_edges.append(edge)
        cursor = prev_node
    path_edges.reverse()
    return distances[end], path_edges


def has_alternative_path(
    node_count: int,
    edges: list[Edge],
    start: int,
    end: int,
    chosen_edge_ids: set[int],
) -> bool:
    disjoint_set = DisjointSet()
    for node in range(node_count):
        disjoint_set.add(node)
    for edge in edges:
        if edge.track_mm == 0.0 and edge.via_mm == 0.0:
            disjoint_set.union(edge.a, edge.b)

    reduced_adjacency: dict[int, list[tuple[int, int]]] = defaultdict(list)
    reduced_edges: dict[int, tuple[int, int]] = {}
    for edge in edges:
        if edge.track_mm == 0.0 and edge.via_mm == 0.0:
            continue
        left = disjoint_set.find(edge.a)
        right = disjoint_set.find(edge.b)
        if left == right:
            continue
        reduced_adjacency[left].append((right, edge.edge_id))
        reduced_adjacency[right].append((left, edge.edge_id))
        reduced_edges[edge.edge_id] = (left, right)

    reduced_start = disjoint_set.find(start)
    reduced_end = disjoint_set.find(end)
    if reduced_start == reduced_end:
        return False

    def can_reach(banned_edge_id: int) -> bool:
        queue = deque([reduced_start])
        visited = {reduced_start}
        while queue:
            node = queue.popleft()
            if node == reduced_end:
                return True
            for neighbor, edge_id in reduced_adjacency.get(node, []):
                if edge_id == banned_edge_id:
                    continue
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                queue.append(neighbor)
        return False

    for edge_id in chosen_edge_ids:
        if edge_id not in reduced_edges:
            continue
        if can_reach(edge_id):
            return True
    return False


def measure(
    board: BoardModel,
    start_selector: str,
    end_selector: str,
    allowed_pass_through_refs: set[str],
    include_via_length: bool,
    allow_alternative_paths: bool,
    auto_pass_through: bool = True,
) -> dict[str, object]:
    start_pad = resolve_pad(board, start_selector)
    end_pad = resolve_pad(board, end_selector)
    ref_by_uuid, uuids_by_ref = build_footprint_ref_maps(board)
    explicit_pass_through_footprints = resolve_pass_through_footprints(board, set(allowed_pass_through_refs))
    all_pass_through_footprints, auto_pass_through_footprints = select_pass_through_footprints(
        board=board,
        left_net=start_pad.net,
        right_net=end_pad.net,
        explicit_pass_through_footprints=explicit_pass_through_footprints,
        auto_pass_through=auto_pass_through,
    )
    auto_pass_through_labels = set(labels_for_footprints(board, auto_pass_through_footprints))

    adjacency, reverse_nodes, edges, endpoint_nodes = build_graph(
        board=board,
        start_pad=start_pad,
        end_pad=end_pad,
        allowed_pass_through_footprints=all_pass_through_footprints,
        include_via_length=include_via_length,
    )
    if include_via_length and not board.stackup.has_via_height_data:
        via_edge_ids = {edge.edge_id for edge in edges if edge.kind == "via"}
        try:
            total_cost_mm, path_edges = shortest_path(
                adjacency,
                endpoint_nodes["start"],
                endpoint_nodes["end"],
                banned_edge_ids=via_edge_ids,
            )
        except ValueError as exc:
            raise ValueError(
                "board stackup does not define via heights for the selected path; rerun with --exclude-via-height to ignore via height"
            ) from exc
    else:
        total_cost_mm, path_edges = shortest_path(adjacency, endpoint_nodes["start"], endpoint_nodes["end"])

    chosen_weighted_edge_ids = {edge.edge_id for edge in path_edges if (edge.track_mm > 0.0 or edge.via_mm > 0.0)}
    if not allow_alternative_paths and has_alternative_path(
        node_count=len(reverse_nodes),
        edges=edges,
        start=endpoint_nodes["start"],
        end=endpoint_nodes["end"],
        chosen_edge_ids=chosen_weighted_edge_ids,
    ):
        raise ValueError("multiple routed path alternatives were found between the selected pads; rerun with --allow-alternative-paths to report the shortest one")

    track_length_mm = sum(edge.track_mm for edge in path_edges)
    via_length_mm = sum(edge.via_mm for edge in path_edges)
    crossed_components = unique_sequence(edge.detail for edge in path_edges if edge.kind == "pass_through")
    auto_crossed_components = [label for label in crossed_components if label in auto_pass_through_labels]
    nets_visited = unique_sequence(edge.net for edge in path_edges if edge.net)

    return {
        "start_pad": pad_display_name(start_pad, ref_by_uuid, uuids_by_ref),
        "end_pad": pad_display_name(end_pad, ref_by_uuid, uuids_by_ref),
        "track_length_mm": track_length_mm,
        "via_length_mm": via_length_mm,
        "total_length_mm": total_cost_mm,
        "pass_through_refs": crossed_components,
        "auto_pass_through_refs": auto_crossed_components,
        "nets_visited": nets_visited,
        "path_edges": path_edges,
        "source_net": start_pad.net,
        "destination_net": end_pad.net,
        "status": "OK",
        "error": None,
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Measure exact routed pad-to-pad signal lengths from a KiCad .kicad_pcb file.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  kicad-signal-path v1.kicad_pcb --start U1:B3 --end J1:H23
  kicad-signal-path v1.kicad_pcb --start U1:B3 --end J1:H23 --auto-pass-through
  kicad-signal-path v1.kicad_pcb --start U1:B3 --end J1:H23 --verbose
  kicad-signal-path v1.kicad_pcb --src-net-regex '/AXIS_I_(.*)/' --dst-net-template '/FMC_AXIS_I_($1)/'
  kicad-signal-path v1.kicad_pcb --src-net-regex '/FMC_AXIS_O_(.*)/' --dst-net-template '/AXIS_O_($1)/'

Selector rules:
  Pad selectors use REF:PAD, for example U1:B3.
  If a reference is duplicated, use REF@uuid8:PAD, for example R25@b8db5c42:1.
  --pass-through accepts REF, REF@uuid8, or uuid:partial-uuid.

Report notes:
  Delta mm is measured against the shortest successful matched row.
  Max diff is the longest successful total minus the shortest successful total.
  Regex batch mode keeps successful rows and marks failed rows as ERROR.
  Pass-through parts are crossed when explicitly listed with --pass-through or auto-selected by default.
  Auto selection only considers exact 2-pin resistor-style refs matching R*.
  Use --no-auto-pass-through to disable auto selection.
""",
    )
    parser.add_argument("board", type=Path, help="Path to the KiCad .kicad_pcb file to inspect.")
    parser.add_argument("--start", help="Start pad selector in REF:PAD form, for example U1:B3.")
    parser.add_argument("--end", help="End pad selector in REF:PAD form, for example J1:H23.")
    parser.add_argument(
        "--src-net-regex",
        help="Regex used to find source nets in batch mode. Use anchors for exact matching, for example ^/AXIS_I_(.*)$.",
    )
    parser.add_argument(
        "--dst-net-template",
        help="Destination net template using $1-style capture substitution, for example /FMC_AXIS_I_$1.",
    )
    parser.add_argument(
        "--pass-through",
        dest="pass_through_refs",
        action="append",
        default=[],
        help="2-pin bridge selector to treat as a zero-length pass-through. Explicit selectors are always included in addition to any default auto-selected resistor-style bridges. Use REF when unique, or REF@uuid8 when duplicated. Repeat for multiple selectors.",
    )
    parser.add_argument(
        "--auto-pass-through",
        dest="auto_pass_through",
        action="store_true",
        default=True,
        help="Auto-select exact 2-pin bridge parts for the chosen net pair, limited to refs matching R*. This is enabled by default.",
    )
    parser.add_argument(
        "--no-auto-pass-through",
        dest="auto_pass_through",
        action="store_false",
        help="Disable default auto-selection of resistor-style pass-through bridges.",
    )
    parser.add_argument(
        "--exclude-via-height",
        action="store_true",
        help="Ignore vertical via height in the reported total. Track and via columns are still reported separately.",
    )
    parser.add_argument(
        "--allow-alternative-paths",
        action="store_true",
        help="Report the shortest path even if multiple routed alternatives exist instead of treating that as an error.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print the edge-by-edge path breakdown after the summary table.",
    )
    return parser


def format_length(value_mm: float) -> str:
    return f"{value_mm:.6f} mm"


def format_length_cell(value_mm: float) -> str:
    if value_mm is None:
        return "-"
    return f"{value_mm:.6f}"


def shorten_cell(value: str, max_width: int) -> str:
    if len(value) <= max_width:
        return value
    if max_width <= 3:
        return value[:max_width]
    return value[: max_width - 3] + "..."


def format_bridge_cell(result: dict[str, object]) -> str:
    pass_through_refs = list(result.get("pass_through_refs", []))
    if not pass_through_refs:
        return "(none)"

    auto_refs = set(result.get("auto_pass_through_refs", []))
    return ", ".join(
        f"{ref} (auto)" if ref in auto_refs else ref
        for ref in pass_through_refs
    )


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    widths = [len(header) for header in headers]
    for row in rows:
        for index, cell in enumerate(row):
            widths[index] = max(widths[index], len(cell))

    separator = "+" + "+".join("-" * (width + 2) for width in widths) + "+"

    def format_row(cells: list[str]) -> str:
        parts = [f" {cell.ljust(widths[index])} " for index, cell in enumerate(cells)]
        return "|" + "|".join(parts) + "|"

    lines = [separator, format_row(headers), separator]
    lines.extend(format_row(row) for row in rows)
    lines.append(separator)
    return "\n".join(lines)


def summarize_results(results: list[dict[str, object]]) -> dict[str, float | int | None]:
    successful_totals = [
        float(result["total_length_mm"])
        for result in results
        if result.get("status") == "OK" and result.get("total_length_mm") is not None
    ]
    if not successful_totals:
        return {
            "successful_count": 0,
            "failed_count": len(results),
            "min_total_mm": None,
            "max_total_mm": None,
            "max_diff_mm": None,
        }

    min_total_mm = min(successful_totals)
    max_total_mm = max(successful_totals)
    return {
        "successful_count": len(successful_totals),
        "failed_count": len(results) - len(successful_totals),
        "min_total_mm": min_total_mm,
        "max_total_mm": max_total_mm,
        "max_diff_mm": max_total_mm - min_total_mm,
    }


def render_results_table(results: list[dict[str, object]], include_via_length: bool) -> str:
    summary = summarize_results(results)
    min_total_mm = summary["min_total_mm"]
    headers = [
        "Source Net",
        "Dest Net",
        "Start",
        "End",
        "Track mm",
        "Via mm",
        "Total mm" if include_via_length else "Total mm (no via)",
        "Delta mm",
        "Bridge",
        "Status",
    ]
    rows: list[list[str]] = []
    for result in results:
        delta_mm = None
        if result.get("status") == "OK" and result.get("total_length_mm") is not None and min_total_mm is not None:
            delta_mm = float(result["total_length_mm"]) - float(min_total_mm)
        rows.append(
            [
                shorten_cell(str(result["source_net"] or ""), 24),
                shorten_cell(str(result["destination_net"] or ""), 24),
                shorten_cell(str(result["start_pad"]), 12),
                shorten_cell(str(result["end_pad"]), 12),
                format_length_cell(result["track_length_mm"]),
                format_length_cell(result["via_length_mm"]),
                format_length_cell(result["total_length_mm"]),
                format_length_cell(delta_mm),
                shorten_cell(format_bridge_cell(result), 24),
                str(result.get("status", "OK")),
            ]
        )
    return render_table(headers, rows)


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    try:
        board = load_board(args.board)
        if args.start and args.end:
            result = measure(
                board=board,
                start_selector=args.start,
                end_selector=args.end,
                allowed_pass_through_refs=set(args.pass_through_refs),
                include_via_length=not args.exclude_via_height,
                allow_alternative_paths=args.allow_alternative_paths,
                auto_pass_through=args.auto_pass_through,
            )
            results = [result]
        elif args.src_net_regex and args.dst_net_template:
            results = resolve_regex_measurements(
                board=board,
                src_net_regex=args.src_net_regex,
                dst_net_template=args.dst_net_template,
                explicit_pass_through_refs=set(args.pass_through_refs),
                include_via_length=not args.exclude_via_height,
                allow_alternative_paths=args.allow_alternative_paths,
                auto_pass_through=args.auto_pass_through,
            )
        else:
            raise ValueError("use either --start/--end or --src-net-regex/--dst-net-template")
    except (BoardParseError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(render_results_table(results, include_via_length=not args.exclude_via_height))

    summary = summarize_results(results)
    if summary["successful_count"] and summary["successful_count"] > 1:
        print()
        print(
            "Matched summary: "
            f"OK={summary['successful_count']}, "
            f"Min total={format_length(summary['min_total_mm'])}, "
            f"Max total={format_length(summary['max_total_mm'])}, "
            f"Max diff={format_length(summary['max_diff_mm'])}"
        )

    error_results = [result for result in results if result.get("status") == "ERROR"]
    if error_results:
        print()
        print("Batch issues:")
        for result in error_results:
            print(f"- {result['source_net']} -> {result['destination_net']}: {result['error']}")

    for index, result in enumerate(results):
        if args.verbose and result.get("status") == "OK":
            if index or results:
                print()
            print(f"Detailed path: {result['start_pad']} -> {result['end_pad']}")
            print("Nets visited: " + (", ".join(result["nets_visited"]) if result["nets_visited"] else "(none)"))
            print("Path breakdown:")
            for edge in result["path_edges"]:
                if edge.kind == "pad":
                    label = f"pad attach {edge.detail}"
                elif edge.kind == "pass_through":
                    label = f"pass through {edge.detail}"
                elif edge.kind == "via":
                    label = f"via {edge.layer}"
                else:
                    label = f"{edge.kind} {edge.layer}"
                print(
                    f"  - {label}: cost={format_length(edge.cost_mm)}, "
                    f"track={format_length(edge.track_mm)}, via={format_length(edge.via_mm)}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
