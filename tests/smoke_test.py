from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

TESTS = Path(__file__).resolve().parent
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from board_factory import write_sample_board


def main() -> None:
    with tempfile.TemporaryDirectory() as temp_dir:
        board_path = write_sample_board(Path(temp_dir) / "synthetic_board.kicad_pcb")

        help_result = subprocess.run(
            [sys.executable, "-m", "kicad_signal_path", "--help"],
            capture_output=True,
            check=True,
            text=True,
        )
        if "kicad-signal-path" not in help_result.stdout:
            raise AssertionError("CLI help output did not contain the expected command name")

        measure_result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kicad_signal_path",
                str(board_path),
                "--start",
                "U1:1",
                "--end",
                "J1:1",
            ],
            capture_output=True,
            check=True,
            text=True,
        )
        if "/AXIS_I_A" not in measure_result.stdout:
            raise AssertionError("Measurement output did not contain the expected source net")
        if "20.000000" not in measure_result.stdout:
            raise AssertionError("Measurement output did not contain the expected total length")
        if "R1 (auto)" not in measure_result.stdout:
            raise AssertionError("Measurement output did not show the expected auto-selected bridge")


if __name__ == "__main__":
    main()
