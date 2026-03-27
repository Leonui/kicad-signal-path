"""Tests for input validation and error handling."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from kicad_signal_path.core import BoardParseError, load_board, parse_sexp
from kicad_signal_path.validation import (
    MAX_FILE_SIZE_BYTES,
    MAX_RECURSION_DEPTH,
    ResourceLimitError,
    ValidationError,
    validate_file_size,
    validate_recursion_depth,
)


class ValidationTests(unittest.TestCase):
    """Test input validation and security limits."""

    def test_file_size_validation_rejects_large_files(self) -> None:
        """Test that files exceeding size limit are rejected."""
        with tempfile.TemporaryDirectory() as tmpdir:
            large_file = Path(tmpdir) / "large.kicad_pcb"
            # Create a file larger than the limit
            large_file.write_text("x" * (MAX_FILE_SIZE_BYTES + 1))

            with self.assertRaisesRegex(ValidationError, "File too large"):
                validate_file_size(large_file)

    def test_file_size_validation_accepts_normal_files(self) -> None:
        """Test that normal-sized files are accepted."""
        with tempfile.TemporaryDirectory() as tmpdir:
            normal_file = Path(tmpdir) / "normal.kicad_pcb"
            normal_file.write_text("(kicad_pcb)")

            # Should not raise
            validate_file_size(normal_file)

    def test_file_size_validation_rejects_missing_files(self) -> None:
        """Test that missing files are rejected."""
        missing_file = Path("/nonexistent/file.kicad_pcb")

        with self.assertRaisesRegex(ValidationError, "File not found"):
            validate_file_size(missing_file)

    def test_recursion_depth_validation_rejects_deep_nesting(self) -> None:
        """Test that excessive recursion depth is rejected."""
        with self.assertRaisesRegex(ResourceLimitError, "Recursion depth"):
            validate_recursion_depth(MAX_RECURSION_DEPTH + 1)

    def test_recursion_depth_validation_accepts_normal_depth(self) -> None:
        """Test that normal recursion depth is accepted."""
        # Should not raise
        validate_recursion_depth(10)
        validate_recursion_depth(MAX_RECURSION_DEPTH)

    def test_parser_rejects_deeply_nested_sexps(self) -> None:
        """Test that parser rejects deeply nested S-expressions."""
        # Create deeply nested S-expression
        depth = MAX_RECURSION_DEPTH + 10
        nested = "(" * depth + "x" + ")" * depth

        with self.assertRaisesRegex(ResourceLimitError, "Recursion depth"):
            parse_sexp(nested)

    def test_parser_handles_unterminated_string(self) -> None:
        """Test that parser handles unterminated quoted strings."""
        with self.assertRaisesRegex(BoardParseError, "unterminated quoted string"):
            parse_sexp('(test "unterminated)')

    def test_parser_handles_unterminated_escape(self) -> None:
        """Test that parser handles unterminated escape sequences."""
        with self.assertRaisesRegex(BoardParseError, "unterminated escape"):
            parse_sexp('(test "escape\\')

    def test_parser_handles_missing_closing_paren(self) -> None:
        """Test that parser handles missing closing parenthesis."""
        with self.assertRaisesRegex(BoardParseError, "missing closing parenthesis"):
            parse_sexp("(test (nested)")

    def test_parser_handles_unexpected_closing_paren(self) -> None:
        """Test that parser handles unexpected closing parenthesis."""
        with self.assertRaisesRegex(BoardParseError, "trailing tokens|unexpected closing parenthesis"):
            parse_sexp("(test) )")

    def test_parser_handles_trailing_tokens(self) -> None:
        """Test that parser handles trailing tokens after root expression."""
        with self.assertRaisesRegex(BoardParseError, "trailing tokens"):
            parse_sexp("(test) extra")

    def test_parser_handles_unexpected_eof(self) -> None:
        """Test that parser handles unexpected end of file."""
        with self.assertRaisesRegex(BoardParseError, "unexpected end of file"):
            parse_sexp("")

    def test_load_board_rejects_non_kicad_pcb(self) -> None:
        """Test that load_board rejects files that aren't kicad_pcb."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.kicad_pcb"
            bad_file.write_text("(not_a_kicad_pcb)")

            with self.assertRaisesRegex(BoardParseError, "not a kicad_pcb board"):
                load_board(bad_file)

    def test_load_board_rejects_string_root(self) -> None:
        """Test that load_board rejects files with string root."""
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_file = Path(tmpdir) / "bad.kicad_pcb"
            bad_file.write_text("just_a_string")

            with self.assertRaisesRegex(BoardParseError, "not a kicad_pcb board"):
                load_board(bad_file)


class FloatingPointTests(unittest.TestCase):
    """Test floating-point comparison edge cases."""

    def test_zero_comparison_with_epsilon(self) -> None:
        """Test that is_zero handles small values correctly."""
        from kicad_signal_path.core import is_zero

        # Should be considered zero
        self.assertTrue(is_zero(0.0))
        self.assertTrue(is_zero(1e-15))
        self.assertTrue(is_zero(-1e-15))

        # Should not be considered zero
        self.assertFalse(is_zero(1e-6))
        self.assertFalse(is_zero(-1e-6))
        self.assertFalse(is_zero(0.001))


if __name__ == "__main__":
    unittest.main()
