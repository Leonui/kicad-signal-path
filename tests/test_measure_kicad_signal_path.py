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

from board_factory import VIA_LENGTH_MM, write_sample_board, write_single_bridge_board
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
        base = Path(cls.temp_dir.name)
        cls.board_path = write_sample_board(base / "synthetic_board.kicad_pcb")
        cls.missing_stackup_path = write_sample_board(base / "missing_stackup.kicad_pcb", include_stackup=False)
        cls.missing_stackup_unrelated_via_path = write_sample_board(
            base / "missing_stackup_unrelated_via.kicad_pcb",
            include_stackup=False,
            include_unrelated_fmc_axis_i_a_via=True,
        )
        cls.ambiguous_board_path = write_sample_board(base / "ambiguous_board.kicad_pcb", include_axis_i_a_probe=True)
        cls.name_only_board_path = write_sample_board(base / "name_only_board.kicad_pcb", net_format="name_only")
        cls.cap_bridge_board_path = write_single_bridge_board(base / "cap_bridge_board.kicad_pcb", bridge_ref="C1")

        cls.board = load_board(cls.board_path)
        cls.board_without_stackup = load_board(cls.missing_stackup_path)
        cls.board_without_stackup_unrelated_via = load_board(cls.missing_stackup_unrelated_via_path)
        cls.ambiguous_board = load_board(cls.ambiguous_board_path)
        cls.name_only_board = load_board(cls.name_only_board_path)
        cls.cap_bridge_board = load_board(cls.cap_bridge_board_path)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.temp_dir.cleanup()

    def test_loader_resolves_real_kicad_net_names(self) -> None:
        pad_map = {pad.identifier: pad.net for pad in self.board.pads}
        self.assertEqual(self.board.nets_by_ordinal["1"], "/AXIS_I_A")
        self.assertEqual(pad_map["U1:1"], "/AXIS_I_A")
        self.assertEqual(self.board.tracks[0].net, "/AXIS_I_A")
        self.assertEqual(self.board.vias[0].net, "/FMC_AXIS_I_B")

    def test_loader_supports_name_only_net_nodes(self) -> None:
        pad_map = {pad.identifier: pad.net for pad in self.name_only_board.pads}
        self.assertEqual(self.name_only_board.nets_by_ordinal, {})
        self.assertEqual(pad_map["U1:1"], "/AXIS_I_A")
        self.assertEqual(self.name_only_board.tracks[0].net, "/AXIS_I_A")
        self.assertEqual(self.name_only_board.vias[0].net, "/FMC_AXIS_I_B")

    def test_single_path_can_disable_default_auto_pass_through(self) -> None:
        with self.assertRaisesRegex(ValueError, "no routed path"):
            measure(
                board=self.board,
                start_selector="U1:1",
                end_selector="J1:1",
                allowed_pass_through_refs=set(),
                include_via_length=True,
                allow_alternative_paths=False,
                auto_pass_through=False,
            )

    def test_single_path_uses_default_auto_pass_through(self) -> None:
        result = measure(
            board=self.board,
            start_selector="U1:1",
            end_selector="J1:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        self.assertEqual(result["pass_through_refs"], ["R1"])
        self.assertEqual(result["auto_pass_through_refs"], ["R1"])
        self.assertEqual(result["nets_visited"], ["/AXIS_I_A", "/FMC_AXIS_I_A"])
        self.assertAlmostEqual(result["track_length_mm"], 20.000000, places=6)
        self.assertAlmostEqual(result["via_length_mm"], 0.000000, places=6)
        self.assertAlmostEqual(result["total_length_mm"], 20.000000, places=6)

    def test_single_path_auto_pass_through_finds_resistor(self) -> None:
        result = measure(
            board=self.board,
            start_selector="U1:1",
            end_selector="J1:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
            auto_pass_through=True,
        )
        self.assertEqual(result["pass_through_refs"], ["R1"])
        self.assertEqual(result["auto_pass_through_refs"], ["R1"])

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
        self.assertEqual(result["auto_pass_through_refs"], ["R2"])
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
        self.assertEqual(result_map["/AXIS_I_A"]["auto_pass_through_refs"], ["R1"])
        self.assertEqual(result_map["/AXIS_I_B"]["auto_pass_through_refs"], ["R2"])

    def test_regex_pair_mode_can_auto_find_resistor_pass_throughs(self) -> None:
        results = resolve_regex_measurements(
            board=self.board,
            src_net_regex="/AXIS_I_(.*)/",
            dst_net_template="/FMC_AXIS_I_($1)/",
            explicit_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
            auto_pass_through=True,
        )
        result_map = {result["source_net"]: result for result in results}
        self.assertEqual(result_map["/AXIS_I_A"]["status"], "OK")
        self.assertEqual(result_map["/AXIS_I_A"]["pass_through_refs"], ["R1"])
        self.assertEqual(result_map["/AXIS_I_A"]["auto_pass_through_refs"], ["R1"])
        self.assertEqual(result_map["/AXIS_I_B"]["pass_through_refs"], ["R2"])
        self.assertEqual(result_map["/AXIS_I_B"]["auto_pass_through_refs"], ["R2"])

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
        self.assertEqual(results[0]["auto_pass_through_refs"], ["R3"])

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

    def test_summary_table_marks_auto_bridges(self) -> None:
        result = measure(
            board=self.board,
            start_selector="U1:1",
            end_selector="J1:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
            auto_pass_through=True,
        )
        table = render_results_table([result], include_via_length=True)
        self.assertIn("R1 (auto)", table)

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

    def test_missing_stackup_still_loads_and_allows_via_free_paths(self) -> None:
        self.assertFalse(self.board_without_stackup.stackup.has_via_height_data)
        result = measure(
            board=self.board_without_stackup,
            start_selector="U1:1",
            end_selector="J1:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        self.assertAlmostEqual(result["total_length_mm"], 20.000000, places=6)

    def test_missing_stackup_ignores_unrelated_vias_on_same_net(self) -> None:
        result = measure(
            board=self.board_without_stackup_unrelated_via,
            start_selector="U1:1",
            end_selector="J1:1",
            allowed_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        self.assertAlmostEqual(result["track_length_mm"], 20.000000, places=6)
        self.assertAlmostEqual(result["via_length_mm"], 0.000000, places=6)
        self.assertAlmostEqual(result["total_length_mm"], 20.000000, places=6)

    def test_missing_stackup_requires_excluding_via_height_for_via_paths(self) -> None:
        with self.assertRaisesRegex(ValueError, "--exclude-via-height"):
            measure(
                board=self.board_without_stackup,
                start_selector="U2:1",
                end_selector="J2:1",
                allowed_pass_through_refs=set(),
                include_via_length=True,
                allow_alternative_paths=False,
            )

    def test_missing_stackup_can_ignore_via_height(self) -> None:
        result = measure(
            board=self.board_without_stackup,
            start_selector="U2:1",
            end_selector="J2:1",
            allowed_pass_through_refs=set(),
            include_via_length=False,
            allow_alternative_paths=False,
        )
        self.assertAlmostEqual(result["track_length_mm"], 20.000000, places=6)
        self.assertAlmostEqual(result["via_length_mm"], 0.000000, places=6)
        self.assertAlmostEqual(result["total_length_mm"], 20.000000, places=6)

    def test_regex_pair_mode_reports_ambiguous_endpoints(self) -> None:
        results = resolve_regex_measurements(
            board=self.ambiguous_board,
            src_net_regex="/AXIS_I_(.*)/",
            dst_net_template="/FMC_AXIS_I_($1)/",
            explicit_pass_through_refs=set(),
            include_via_length=True,
            allow_alternative_paths=False,
        )
        result_map = {result["source_net"]: result for result in results}
        self.assertEqual(result_map["/AXIS_I_A"]["status"], "ERROR")
        self.assertIn("multiple possible endpoint pads", result_map["/AXIS_I_A"]["error"])
        self.assertIn("TP1:1", result_map["/AXIS_I_A"]["error"])
        self.assertEqual(result_map["/AXIS_I_B"]["status"], "OK")

    def test_auto_pass_through_does_not_pick_non_resistor_refs(self) -> None:
        with self.assertRaisesRegex(ValueError, "no routed path"):
            measure(
                board=self.cap_bridge_board,
                start_selector="U1:1",
                end_selector="J1:1",
                allowed_pass_through_refs=set(),
                include_via_length=True,
                allow_alternative_paths=False,
            )


if __name__ == "__main__":
    unittest.main()
