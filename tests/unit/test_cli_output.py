"""Tests for the shared CLI output module."""

from openclaw.cli.output import err, header, info, ok, warn


class TestOutputHelpers:
    def test_ok_prints_checkmark(self, capsys: object) -> None:
        ok("test message")
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "test message" in captured.out

    def test_warn_prints_message(self, capsys: object) -> None:
        warn("warning here")
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "warning here" in captured.out

    def test_err_prints_message(self, capsys: object) -> None:
        err("error here")
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "error here" in captured.out

    def test_info_prints_message(self, capsys: object) -> None:
        info("info here")
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "info here" in captured.out

    def test_header_prints_title(self, capsys: object) -> None:
        header("My Section")
        captured = capsys.readouterr()  # type: ignore[union-attr]
        assert "My Section" in captured.out
        # Should contain horizontal rules
        assert "\u2500" in captured.out
