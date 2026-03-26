# kicad-signal-path

`kicad-signal-path` measures exact routed pad-to-pad signal lengths directly from KiCad `.kicad_pcb` files.

It supports:

- single pad-to-pad path measurement
- regex-based source and destination net matching
- automatic 2-pin bridge detection for series resistors and similar pass-through parts
- separate `Track mm`, `Via mm`, `Total mm`, and `Delta mm` reporting
- CLI and Python usage from the same package

## Install

Run it without installing:

```bash
uvx kicad-signal-path --help
```

Install it as a CLI tool:

```bash
uv tool install kicad-signal-path
```

Add it to a Python project:

```bash
uv add kicad-signal-path
```

## Quick Start

Single path measurement:

```bash
kicad-signal-path board.kicad_pcb --start U1:B3 --end J1:H23
```

Regex batch matching:

```bash
kicad-signal-path \
  board.kicad_pcb \
  --src-net-regex '/AXIS_I_(.*)/' \
  --dst-net-template '/FMC_AXIS_I_($1)/'
```

Verbose path breakdown:

```bash
kicad-signal-path \
  board.kicad_pcb \
  --start U1:B3 \
  --end J1:H23 \
  --verbose
```

Use the module form if you prefer:

```bash
python -m kicad_signal_path --help
```

## Development

Create a local environment and install the project in editable mode through `uv`:

```bash
uv sync --dev
```

Run tests:

```bash
uv run pytest
```

Build distributable artifacts:

```bash
uv build --no-sources
```

Local smoke test against built artifacts:

```bash
uv run --isolated --no-project --with dist/*.whl tests/smoke_test.py
uv run --isolated --no-project --with dist/*.tar.gz tests/smoke_test.py
```

## Release

This repo is prepared for public PyPI publishing with `uv` and GitHub Actions.

1. Create the PyPI project `kicad-signal-path`.
2. In PyPI trusted publishing, allow GitHub repository `Leonui/kicad-signal-path`.
3. Set the trusted publishing workflow to `.github/workflows/publish.yml`.
4. Set the trusted publishing environment name to `pypi`.
5. Push a version tag such as `v0.1.0`.

Manual local publish also works after authentication is configured:

```bash
uv publish
```

## Test Data

This repository intentionally ships no KiCad board design files. Tests generate a small synthetic board description at runtime so the package can be validated without bundling proprietary PCB data.
