from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
TESTS = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

from board_factory import VIA_LENGTH_MM, write_sample_board
from kicad_signal_path import (
    load_board,
    measure,
    render_results_table,
    resolve_regex_measurements,
    summarize_results,
)


class MeasureKicadSignalPathTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.board_path = write_sample_board(Path(cls.temp_dir.name) / "synthetic_board.txt")
        cls.board = load_board(cls.board_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_single_path_auto_detects_series_resistor(self) -> None:
        result = measure(
            board=self.board,
            start_selector="U1:1",
            end_selector="J1:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        self.assertEqual(result["pass_through_refs"], ["R1"])
        self.assertEqual(result["nets_visited"], ["/AXIS_I_A", "/FMC_AXIS_I_A"])
        self.assertAlmostEqual(result["track_length_mm"], 20.000000, places=6)
        self.assertAlmostEqual(result["via_length_mm"], 0.000000, places=6)
        self.assertAlmostEqual(result["total_length_mm"], 20.000000, places=6)

    def test_single_path_reports_via_length(self) -> None:
        result = measure(
            board=self.board,
            start_selector="U2:1",
            end_selector="J2:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        self.assertEqual(result["pass_through_refs"], ["R2"])
        self.assertAlmostEqual(result["track_length_mm"], 20.000000, places=6)
        self.assertAlmostEqual(result["via_length_mm"], VIA_LENGTH_MM, places=6)
        self.assertAlmostEqual(result["total_length_mm"], 20.000000 + VIA_LENGTH_MM, places=6)

    def test_regex_pair_mode_matches_input_lanes(self) -> None:
        results = resolve_regex_measurements(
            board=self.board,
            src_net_regex="/AXIS_I_(.*)/",
            dst_net_template="/FMC_AXIS_I_($1)/",
            explicit_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        result_map = {result["source_net"]: result for result in results}
        self.assertEqual(sorted(result_map), ["/AXIS_I_A", "/AXIS_I_B"])
        self.assertEqual(result_map["/AXIS_I_A"]["pass_through_refs"], ["R1"])
        self.assertEqual(result_map["/AXIS_I_B"]["pass_through_refs"], ["R2"])

    def test_regex_pair_mode_handles_output_direction(self) -> None:
        results = resolve_regex_measurements(
            board=self.board,
            src_net_regex="/FMC_AXIS_O_(DATA)/",
            dst_net_template="/AXIS_O_($1)/",
            explicit_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["start_pad"], "J3:1")
        self.assertEqual(results[0]["end_pad"], "U3:1")
        self.assertEqual(results[0]["pass_through_refs"], ["R3"])

    def test_summary_table_contains_expected_columns_and_values(self) -> None:
        result = measure(
            board=self.board,
            start_selector="U2:1",
            end_selector="J2:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        table = render_results_table([result], include_via_length=True)
        self.assertIn("Source Net", table)
        self.assertIn("Dest Net", table)
        self.assertIn("Delta mm", table)
        self.assertIn("/AXIS_I_B", table)
        self.assertIn("/FMC_AXIS_I_B", table)
        self.assertIn("20.235000", table)
        self.assertIn("0.000000", table)

    def test_summary_metrics_report_max_diff(self) -> None:
        results = resolve_regex_measurements(
            board=self.board,
            src_net_regex="/AXIS_I_(.*)/",
            dst_net_template="/FMC_AXIS_I_($1)/",
            explicit_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        summary = summarize_results(results)
        self.assertEqual(summary["successful_count"], 2)
        self.assertEqual(summary["failed_count"], 0)
        self.assertAlmostEqual(summary["min_total_mm"], 20.000000, places=6)
        self.assertAlmostEqual(summary["max_total_mm"], 20.000000 + VIA_LENGTH_MM, places=6)
        self.assertAlmostEqual(summary["max_diff_mm"], VIA_LENGTH_MM, places=6)


if __name__ == "__main__":
    unittest.main()
