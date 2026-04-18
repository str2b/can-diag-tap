from __future__ import annotations

from can_diag_trace import TraceAnalyzer, setup_parser


def test_trace_analyzer_symbol_is_exported() -> None:
    assert TraceAnalyzer is not None


def test_trace_parser_accepts_trace_argument() -> None:
    args = setup_parser().parse_args(["-t", "example.asc"])
    assert args.trace_file == "example.asc"