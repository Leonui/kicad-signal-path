"""Module entrypoint for ``python -m kicad_signal_path``."""

from .cli import main


if __name__ == "__main__":
    raise SystemExit(main())
