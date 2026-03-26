from __future__ import annotations

from pathlib import Path


F_CU = "F.Cu"
B_CU = "B.Cu"
ALL_CU = "*.Cu"
VIA_LENGTH_MM = 0.235


def _quoted(value: str) -> str:
    return f'"{value}"'


def _pad(
    number: str,
    kind: str,
    shape: str,
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
        f"      (net {_quoted(net)}))"
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


def _segment(net: str, layer: str, start: tuple[float, float], end: tuple[float, float]) -> str:
    return (
        f"  (segment\n"
        f"    (start {start[0]:.3f} {start[1]:.3f})\n"
        f"    (end {end[0]:.3f} {end[1]:.3f})\n"
        f"    (layer {_quoted(layer)})\n"
        f"    (net {_quoted(net)}))"
    )


def _via(net: str, at: tuple[float, float], layers: tuple[str, ...]) -> str:
    layer_values = " ".join(_quoted(layer) for layer in layers)
    return (
        f"  (via\n"
        f"    (at {at[0]:.3f} {at[1]:.3f})\n"
        f"    (layers {layer_values})\n"
        f"    (net {_quoted(net)}))"
    )


def build_sample_board() -> str:
    parts = [
        "(kicad_pcb",
        "  (setup",
        "    (stackup",
        f'      (layer {_quoted(F_CU)} (type {_quoted("copper")}) (thickness 0.035))',
        f'      (layer {_quoted("dielectric 1")} (type {_quoted("core")}) (thickness 0.200))',
        f'      (layer {_quoted(B_CU)} (type {_quoted("copper")}) (thickness 0.035))',
        "    )",
        "  )",
        _footprint(
            "U1",
            "u1-uuid",
            0.0,
            0.0,
            [
                _pad("1", "thru_hole", "circle", layers=(ALL_CU,), net="/AXIS_I_A"),
            ],
        ),
        _footprint(
            "J1",
            "j1-uuid",
            30.0,
            0.0,
            [
                _pad("1", "thru_hole", "circle", layers=(ALL_CU,), net="/FMC_AXIS_I_A"),
            ],
        ),
        _footprint(
            "R1",
            "r1-uuid",
            15.0,
            0.0,
            [
                _pad("1", "smd", "rect", at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/AXIS_I_A"),
                _pad("2", "smd", "rect", at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_I_A"),
            ],
        ),
        _footprint(
            "U2",
            "u2-uuid",
            0.0,
            10.0,
            [
                _pad("1", "thru_hole", "circle", layers=(ALL_CU,), net="/AXIS_I_B"),
            ],
        ),
        _footprint(
            "J2",
            "j2-uuid",
            30.0,
            10.0,
            [
                _pad("1", "thru_hole", "circle", layers=(ALL_CU,), net="/FMC_AXIS_I_B"),
            ],
        ),
        _footprint(
            "R2",
            "r2-uuid",
            15.0,
            10.0,
            [
                _pad("1", "smd", "rect", at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/AXIS_I_B"),
                _pad("2", "smd", "rect", at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_I_B"),
            ],
        ),
        _footprint(
            "J3",
            "j3-uuid",
            0.0,
            20.0,
            [
                _pad("1", "thru_hole", "circle", layers=(ALL_CU,), net="/FMC_AXIS_O_DATA"),
            ],
        ),
        _footprint(
            "U3",
            "u3-uuid",
            30.0,
            20.0,
            [
                _pad("1", "thru_hole", "circle", layers=(ALL_CU,), net="/AXIS_O_DATA"),
            ],
        ),
        _footprint(
            "R3",
            "r3-uuid",
            15.0,
            20.0,
            [
                _pad("1", "smd", "rect", at=(-5.0, 0.0, 0.0), layers=(F_CU,), net="/FMC_AXIS_O_DATA"),
                _pad("2", "smd", "rect", at=(5.0, 0.0, 0.0), layers=(F_CU,), net="/AXIS_O_DATA"),
            ],
        ),
        _segment("/AXIS_I_A", F_CU, (0.0, 0.0), (10.0, 0.0)),
        _segment("/FMC_AXIS_I_A", F_CU, (20.0, 0.0), (30.0, 0.0)),
        _segment("/AXIS_I_B", F_CU, (0.0, 10.0), (10.0, 10.0)),
        _segment("/FMC_AXIS_I_B", F_CU, (20.0, 10.0), (25.0, 10.0)),
        _via("/FMC_AXIS_I_B", (25.0, 10.0), (F_CU, B_CU)),
        _segment("/FMC_AXIS_I_B", B_CU, (25.0, 10.0), (30.0, 10.0)),
        _segment("/FMC_AXIS_O_DATA", F_CU, (0.0, 20.0), (10.0, 20.0)),
        _segment("/AXIS_O_DATA", F_CU, (20.0, 20.0), (30.0, 20.0)),
        ")",
    ]
    return "\n".join(parts) + "\n"


def write_sample_board(path: Path) -> Path:
    path.write_text(build_sample_board(), encoding="utf-8")
    return path
