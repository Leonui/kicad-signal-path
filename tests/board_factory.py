from __future__ import annotations

from pathlib import Path


F_CU = "F.Cu"
B_CU = "B.Cu"
ALL_CU = "*.Cu"
VIA_LENGTH_MM = 0.235

NET_ORDINALS = {
    "": 0,
    "/AXIS_I_A": 1,
    "/FMC_AXIS_I_A": 2,
    "/AXIS_I_B": 3,
    "/FMC_AXIS_I_B": 4,
    "/FMC_AXIS_O_DATA": 5,
    "/AXIS_O_DATA": 6,
    "/FMC_AXIS_I_A_LB": 7,
}

LAYER_ORDINALS = {
    F_CU: 0,
    B_CU: 31,
}


def _quoted(value: str) -> str:
    return f'"{value}"'


def _net_name(net: str) -> str:
    return _quoted(net) if net else '""'


def _net_ordinal(net: str) -> int:
    return NET_ORDINALS[net]


def _net_attr(net: str, net_format: str) -> str:
    if net_format == "name_only":
        return _net_name(net)
    return f"{_net_ordinal(net)} {_net_name(net)}"


def _route_net_attr(net: str, net_format: str) -> str:
    if net_format == "name_only":
        return _net_name(net)
    return str(_net_ordinal(net))


def _board_layers() -> str:
    return "\n".join(
        [
            "  (layers",
            f'    ({LAYER_ORDINALS[F_CU]} {_quoted(F_CU)} signal)',
            f'    ({LAYER_ORDINALS[B_CU]} {_quoted(B_CU)} signal)',
            "  )",
        ]
    )


def _stackup() -> str:
    return "\n".join(
        [
            "  (setup",
            "    (stackup",
            f'      (layer {_quoted(F_CU)} {LAYER_ORDINALS[F_CU]} (type {_quoted("copper")}) (thickness 0.035))',
            '      (layer "dielectric" 1 (type "core") (thickness 0.200))',
            f'      (layer {_quoted(B_CU)} {LAYER_ORDINALS[B_CU]} (type {_quoted("copper")}) (thickness 0.035))',
            "    )",
            "  )",
        ]
    )


def _empty_setup() -> str:
    return "  (setup)"


def _net_defs() -> list[str]:
    return [f"  (net {ordinal} {_net_name(net)})" for net, ordinal in NET_ORDINALS.items()]


def _pad(
    number: str,
    kind: str,
    shape: str,
    net_format: str,
    *,
    at: tuple[float, float, float] = (0.0, 0.0, 0.0),
    size: tuple[float, float] = (2.0, 2.0),
    layers: tuple[str, ...],
    net: str,
) -> str:
    x, y, angle = at
    width, height = size
    layer_values = " ".join(_quoted(layer) for layer in layers)
    return (
        f'    (pad {_quoted(number)} {kind} {shape}\n'
        f"      (at {x:.3f} {y:.3f} {angle:.3f})\n"
        f"      (size {width:.3f} {height:.3f})\n"
        f"      (layers {layer_values})\n"
        f"      (net {_net_attr(net, net_format)}))"
    )


def _footprint(ref: str, uuid: str, x: float, y: float, pads: list[str]) -> str:
    pads_text = "\n".join(pads)
    return (
        f'  (footprint "Synthetic:{ref}"\n'
        f'    (property "Reference" {_quoted(ref)})\n'
        f"    (uuid {_quoted(uuid)})\n"
        f"    (at {x:.3f} {y:.3f} 0.000)\n"
        f"{pads_text}\n"
        f"  )"
    )


def _segment(net: str, layer: str, start: tuple[float, float], end: tuple[float, float], *, net_format: str) -> str:
    return (
        f"  (segment\n"
        f"    (start {start[0]:.3f} {start[1]:.3f})\n"
        f"    (end {end[0]:.3f} {end[1]:.3f})\n"
        f"    (layer {_quoted(layer)})\n"
        f"    (net {_route_net_attr(net, net_format)}))"
    )


def _via(
    net: str,
    at: tuple[float, float],
    layers: tuple[str, ...],
    *,
    net_format: str,
    size: float = 0.6,
) -> str:
    layer_values = " ".join(_quoted(layer) for layer in layers)
    return (
        f"  (via\n"
        f"    (at {at[0]:.3f} {at[1]:.3f})\n"
        f"    (size {size:.3f})\n"
        f"    (layers {layer_values})\n"
        f"    (net {_route_net_attr(net, net_format)}))"
    )


def build_sample_board(
    *,
    include_stackup: bool = True,
    include_axis_i_a_probe: bool = False,
    include_unrelated_fmc_axis_i_a_via: bool = False,
    include_fmc_axis_i_a_branch_bridge: bool = False,
    net_format: str = "ordinal",
) -> str:
    if net_format not in {"ordinal", "name_only"}:
        raise ValueError(f"unsupported net format '{net_format}'")

    parts = [
        "(kicad_pcb",
        _board_layers(),
        _stackup() if include_stackup else _empty_setup(),
    ]
    if net_format == "ordinal":
        parts.extend(_net_defs())

    parts.extend(
        [
            _footprint(
                "U1",
                "u1-uuid",
                0.0,
                0.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/AXIS_I_A"),
                ],
            ),
            _footprint(
                "J1",
                "j1-uuid",
                30.0,
                0.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/FMC_AXIS_I_A"),
                ],
            ),
            _footprint(
                "R1",
                "r1-uuid",
                15.0,
                0.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/AXIS_I_A"),
                    _pad("2", "smd", "rect", net_format, at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_I_A"),
                ],
            ),
            _footprint(
                "U2",
                "u2-uuid",
                0.0,
                10.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/AXIS_I_B"),
                ],
            ),
            _footprint(
                "J2",
                "j2-uuid",
                30.0,
                10.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/FMC_AXIS_I_B"),
                ],
            ),
            _footprint(
                "R2",
                "r2-uuid",
                15.0,
                10.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/AXIS_I_B"),
                    _pad("2", "smd", "rect", net_format, at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_I_B"),
                ],
            ),
            _footprint(
                "J3",
                "j3-uuid",
                0.0,
                20.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/FMC_AXIS_O_DATA"),
                ],
            ),
            _footprint(
                "U3",
                "u3-uuid",
                30.0,
                20.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/AXIS_O_DATA"),
                ],
            ),
            _footprint(
                "R3",
                "r3-uuid",
                15.0,
                20.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_O_DATA"),
                    _pad("2", "smd", "rect", net_format, at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/AXIS_O_DATA"),
                ],
            ),
        ]
    )

    if include_axis_i_a_probe:
        parts.append(
            _footprint(
                "TP1",
                "tp1-uuid",
                5.0,
                -5.0,
                [
                    _pad("1", "smd", "circle", net_format, layers=(F_CU,), net="/AXIS_I_A"),
                ],
            )
        )

    if include_fmc_axis_i_a_branch_bridge:
        parts.append(
            _footprint(
                "R4",
                "r4-uuid",
                25.0,
                5.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_I_A"),
                    _pad("2", "smd", "rect", net_format, at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_I_A_LB"),
                ],
            )
        )

    if include_unrelated_fmc_axis_i_a_via:
        parts.append(_via("/FMC_AXIS_I_A", (24.000, 4.000), (F_CU, B_CU), net_format=net_format))

    parts.extend(
        [
            _segment("/AXIS_I_A", F_CU, (0.0, 0.0), (10.0, 0.0), net_format=net_format),
            _segment("/FMC_AXIS_I_A", F_CU, (20.0, 0.0), (30.0, 0.0), net_format=net_format),
            _segment("/AXIS_I_B", F_CU, (0.0, 10.0), (10.0, 10.0), net_format=net_format),
            _segment("/FMC_AXIS_I_B", F_CU, (20.0, 10.0), (25.0, 10.0), net_format=net_format),
            _via("/FMC_AXIS_I_B", (25.0, 10.0), (F_CU, B_CU), net_format=net_format),
            _segment("/FMC_AXIS_I_B", B_CU, (25.0, 10.0), (30.0, 10.0), net_format=net_format),
            _segment("/FMC_AXIS_O_DATA", F_CU, (0.0, 20.0), (10.0, 20.0), net_format=net_format),
            _segment("/AXIS_O_DATA", F_CU, (20.0, 20.0), (30.0, 20.0), net_format=net_format),
            ")",
        ]
    )
    return "\n".join(parts) + "\n"


def write_sample_board(
    path: Path,
    *,
    include_stackup: bool = True,
    include_axis_i_a_probe: bool = False,
    include_unrelated_fmc_axis_i_a_via: bool = False,
    include_fmc_axis_i_a_branch_bridge: bool = False,
    net_format: str = "ordinal",
) -> Path:
    path.write_text(
        build_sample_board(
            include_stackup=include_stackup,
            include_axis_i_a_probe=include_axis_i_a_probe,
            include_unrelated_fmc_axis_i_a_via=include_unrelated_fmc_axis_i_a_via,
            include_fmc_axis_i_a_branch_bridge=include_fmc_axis_i_a_branch_bridge,
            net_format=net_format,
        ),
        encoding="utf-8",
    )
    return path


def write_single_bridge_board(
    path: Path,
    *,
    bridge_ref: str,
    net_format: str = "name_only",
) -> Path:
    if net_format not in {"ordinal", "name_only"}:
        raise ValueError(f"unsupported net format '{net_format}'")

    local_net_ordinals = {"": 0, "/A": 1, "/B": 2}

    def local_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return f'{local_net_ordinals[net]} {_net_name(net)}'

    def local_route_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return str(local_net_ordinals[net])

    parts = [
        "(kicad_pcb",
        _board_layers(),
        _stackup(),
    ]
    if net_format == "ordinal":
        parts.extend(
            [
                "  (net 0 \"\")",
                "  (net 1 \"/A\")",
                "  (net 2 \"/B\")",
            ]
        )

    parts.extend(
        [
            _footprint(
                "U1",
                "u1-uuid",
                0.0,
                0.0,
                [
                    '    (pad "1" thru_hole circle\n'
                    '      (at 0.000 0.000 0.000)\n'
                    '      (size 2.000 2.000)\n'
                    f'      (layers "{ALL_CU}")\n'
                    f"      (net {local_net_attr('/A')}))",
                ],
            ),
            _footprint(
                "J1",
                "j1-uuid",
                30.0,
                0.0,
                [
                    '    (pad "1" thru_hole circle\n'
                    '      (at 0.000 0.000 0.000)\n'
                    '      (size 2.000 2.000)\n'
                    f'      (layers "{ALL_CU}")\n'
                    f"      (net {local_net_attr('/B')}))",
                ],
            ),
            _footprint(
                bridge_ref,
                "bridge-uuid",
                15.0,
                0.0,
                [
                    '    (pad "1" smd rect\n'
                    '      (at -5.000 0.000 0.000)\n'
                    '      (size 2.000 2.000)\n'
                    f'      (layers "{F_CU}")\n'
                    f"      (net {local_net_attr('/A')}))",
                    '    (pad "2" smd rect\n'
                    '      (at 5.000 0.000 0.000)\n'
                    '      (size 2.000 2.000)\n'
                    f'      (layers "{F_CU}")\n'
                    f"      (net {local_net_attr('/B')}))",
                ],
            ),
            (
                "  (segment\n"
                "    (start 0.000 0.000)\n"
                "    (end 10.000 0.000)\n"
                f'    (layer "{F_CU}")\n'
                f"    (net {local_route_net_attr('/A')}))"
            ),
            (
                "  (segment\n"
                "    (start 20.000 0.000)\n"
                "    (end 30.000 0.000)\n"
                f'    (layer "{F_CU}")\n'
                f"    (net {local_route_net_attr('/B')}))"
            ),
            ")",
        ]
    )
    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def write_off_center_via_board(path: Path, *, net_format: str = "name_only") -> Path:
    if net_format not in {"ordinal", "name_only"}:
        raise ValueError(f"unsupported net format '{net_format}'")

    local_net_ordinals = {"": 0, "/N": 1}

    def local_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return f'{local_net_ordinals[net]} {_net_name(net)}'

    def local_route_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return str(local_net_ordinals[net])

    parts = [
        "(kicad_pcb",
        _board_layers(),
        _stackup(),
    ]
    if net_format == "ordinal":
        parts.extend(
            [
                "  (net 0 \"\")",
                "  (net 1 \"/N\")",
            ]
        )

    parts.extend(
        [
            _footprint(
                "U1",
                "u1-uuid",
                0.0,
                0.0,
                [
                    '    (pad "1" thru_hole circle\n'
                    '      (at 0.000 0.000 0.000)\n'
                    '      (size 2.000 2.000)\n'
                    f'      (layers "{ALL_CU}")\n'
                    f"      (net {local_net_attr('/N')}))",
                ],
            ),
            _footprint(
                "J1",
                "j1-uuid",
                30.0,
                0.0,
                [
                    '    (pad "1" thru_hole circle\n'
                    '      (at 0.000 0.000 0.000)\n'
                    '      (size 2.000 2.000)\n'
                    f'      (layers "{ALL_CU}")\n'
                    f"      (net {local_net_attr('/N')}))",
                ],
            ),
            (
                "  (segment\n"
                "    (start 0.000 0.000)\n"
                "    (end 20.000 0.000)\n"
                f'    (layer "{F_CU}")\n'
                f"    (net {local_route_net_attr('/N')}))"
            ),
            _via("/N", (20.0, 0.0), (F_CU, B_CU), net_format=net_format, size=1.0),
            (
                "  (segment\n"
                "    (start 19.600 0.200)\n"
                "    (end 30.000 0.000)\n"
                f'    (layer "{B_CU}")\n'
                f"    (net {local_route_net_attr('/N')}))"
            ),
            ")",
        ]
    )

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def write_multi_segment_match_board(path: Path, *, net_format: str = "name_only") -> Path:
    if net_format not in {"ordinal", "name_only"}:
        raise ValueError(f"unsupported net format '{net_format}'")

    local_net_ordinals = {
        "": 0,
        "/BUS_A": 1,
        "/DST_A": 2,
        "/BUS_B": 3,
        "/DST_B": 4,
    }

    def local_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return f'{local_net_ordinals[net]} {_net_name(net)}'

    def local_route_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return str(local_net_ordinals[net])

    def local_segment(net: str, start_x: float, end_x: float, y: float) -> str:
        return (
            "  (segment\n"
            f"    (start {start_x:.3f} {y:.3f})\n"
            f"    (end {end_x:.3f} {y:.3f})\n"
            f'    (layer "{F_CU}")\n'
            f"    (net {local_route_net_attr(net)}))"
        )

    def segment_chain(net: str, start_x: float, y: float, lengths: list[float]) -> list[str]:
        segments: list[str] = []
        cursor_x = start_x
        for length in lengths:
            next_x = cursor_x + length
            segments.append(local_segment(net, cursor_x, next_x, y))
            cursor_x = next_x
        return segments

    parts = [
        "(kicad_pcb",
        _board_layers(),
        _stackup(),
    ]
    if net_format == "ordinal":
        parts.extend(
            [
                "  (net 0 \"\")",
                "  (net 1 \"/BUS_A\")",
                "  (net 2 \"/DST_A\")",
                "  (net 3 \"/BUS_B\")",
                "  (net 4 \"/DST_B\")",
            ]
        )

    parts.extend(
        [
            _footprint(
                "U1",
                "u1-uuid",
                0.0,
                0.0,
                [
                    _pad(
                        "1",
                        "thru_hole",
                        "circle",
                        net_format,
                        layers=(ALL_CU,),
                        net="/BUS_A",
                        size=(0.4, 0.4),
                    ),
                ],
            ),
            _footprint(
                "J1",
                "j1-uuid",
                8.2,
                0.0,
                [
                    _pad(
                        "1",
                        "thru_hole",
                        "circle",
                        net_format,
                        layers=(ALL_CU,),
                        net="/DST_A",
                        size=(0.4, 0.4),
                    ),
                ],
            ),
            _footprint(
                "R1",
                "r1-uuid",
                4.1,
                0.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-0.5, 0.0, 0.0), layers=(F_CU,), net="/BUS_A", size=(0.4, 0.4)),
                    _pad("2", "smd", "rect", net_format, at=(0.5, 0.0, 0.0), layers=(F_CU,), net="/DST_A", size=(0.4, 0.4)),
                ],
            ),
            _footprint(
                "U2",
                "u2-uuid",
                0.0,
                10.0,
                [
                    _pad(
                        "1",
                        "thru_hole",
                        "circle",
                        net_format,
                        layers=(ALL_CU,),
                        net="/BUS_B",
                        size=(0.4, 0.4),
                    ),
                ],
            ),
            _footprint(
                "J2",
                "j2-uuid",
                8.6,
                10.0,
                [
                    _pad(
                        "1",
                        "thru_hole",
                        "circle",
                        net_format,
                        layers=(ALL_CU,),
                        net="/DST_B",
                        size=(0.4, 0.4),
                    ),
                ],
            ),
            _footprint(
                "R2",
                "r2-uuid",
                4.5,
                10.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-0.5, 0.0, 0.0), layers=(F_CU,), net="/BUS_B", size=(0.4, 0.4)),
                    _pad("2", "smd", "rect", net_format, at=(0.5, 0.0, 0.0), layers=(F_CU,), net="/DST_B", size=(0.4, 0.4)),
                ],
            ),
        ]
    )

    parts.extend(segment_chain("/BUS_A", 0.0, 0.0, [0.6, 0.6, 0.6, 0.6, 0.6, 0.6]))
    parts.extend(segment_chain("/DST_A", 4.6, 0.0, [0.6, 0.6, 0.6, 0.6, 0.6, 0.6]))
    parts.extend(segment_chain("/BUS_B", 0.0, 10.0, [0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 0.4]))
    parts.extend(segment_chain("/DST_B", 5.0, 10.0, [0.6, 0.6, 0.6, 0.6, 0.6, 0.6]))
    parts.append(")")

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path


def write_prefer_existing_snake_board(path: Path, *, net_format: str = "name_only") -> Path:
    if net_format not in {"ordinal", "name_only"}:
        raise ValueError(f"unsupported net format '{net_format}'")

    local_net_ordinals = {
        "": 0,
        "/SNAKE_A": 1,
        "/SNAKE_DST_A": 2,
        "/SNAKE_B": 3,
        "/SNAKE_DST_B": 4,
    }

    def local_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return f'{local_net_ordinals[net]} {_net_name(net)}'

    def local_route_net_attr(net: str) -> str:
        if net_format == "name_only":
            return _net_name(net)
        return str(local_net_ordinals[net])

    def local_segment(net: str, start: tuple[float, float], end: tuple[float, float]) -> str:
        return (
            "  (segment\n"
            f"    (start {start[0]:.3f} {start[1]:.3f})\n"
            f"    (end {end[0]:.3f} {end[1]:.3f})\n"
            f'    (layer "{F_CU}")\n'
            f"    (net {local_route_net_attr(net)}))"
        )

    parts = [
        "(kicad_pcb",
        _board_layers(),
        _stackup(),
    ]
    if net_format == "ordinal":
        parts.extend(
            [
                "  (net 0 \"\")",
                "  (net 1 \"/SNAKE_A\")",
                "  (net 2 \"/SNAKE_DST_A\")",
                "  (net 3 \"/SNAKE_B\")",
                "  (net 4 \"/SNAKE_DST_B\")",
            ]
        )

    parts.extend(
        [
            _footprint(
                "U1",
                "snake-u1-uuid",
                0.0,
                0.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/SNAKE_A", size=(0.4, 0.4)),
                ],
            ),
            _footprint(
                "J1",
                "snake-j1-uuid",
                14.0,
                0.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/SNAKE_DST_A", size=(0.4, 0.4)),
                ],
            ),
            _footprint(
                "R1",
                "snake-r1-uuid",
                3.5,
                0.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-0.5, 0.0, 0.0), layers=(F_CU,), net="/SNAKE_A", size=(0.4, 0.4)),
                    _pad("2", "smd", "rect", net_format, at=(0.5, 0.0, 0.0), layers=(F_CU,), net="/SNAKE_DST_A", size=(0.4, 0.4)),
                ],
            ),
            _footprint(
                "U2",
                "snake-u2-uuid",
                0.0,
                10.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/SNAKE_B", size=(0.4, 0.4)),
                ],
            ),
            _footprint(
                "J2",
                "snake-j2-uuid",
                11.0,
                10.0,
                [
                    _pad("1", "thru_hole", "circle", net_format, layers=(ALL_CU,), net="/SNAKE_DST_B", size=(0.4, 0.4)),
                ],
            ),
            _footprint(
                "R2",
                "snake-r2-uuid",
                3.5,
                10.0,
                [
                    _pad("1", "smd", "rect", net_format, at=(-0.5, 0.0, 0.0), layers=(F_CU,), net="/SNAKE_B", size=(0.4, 0.4)),
                    _pad("2", "smd", "rect", net_format, at=(0.5, 0.0, 0.0), layers=(F_CU,), net="/SNAKE_DST_B", size=(0.4, 0.4)),
                ],
            ),
            local_segment("/SNAKE_A", (0.0, 0.0), (3.0, 0.0)),
            local_segment("/SNAKE_DST_A", (4.0, 0.0), (14.0, 0.0)),
            local_segment("/SNAKE_B", (0.0, 10.0), (3.0, 10.0)),
            local_segment("/SNAKE_DST_B", (4.0, 10.0), (5.0, 10.0)),
            local_segment("/SNAKE_DST_B", (5.0, 10.0), (5.0, 11.0)),
            local_segment("/SNAKE_DST_B", (5.0, 11.0), (9.0, 11.0)),
            local_segment("/SNAKE_DST_B", (9.0, 11.0), (9.0, 10.0)),
            local_segment("/SNAKE_DST_B", (9.0, 10.0), (10.0, 10.0)),
            local_segment("/SNAKE_DST_B", (10.0, 10.0), (11.0, 10.0)),
            ")",
        ]
    )

    path.write_text("\n".join(parts) + "\n", encoding="utf-8")
    return path
