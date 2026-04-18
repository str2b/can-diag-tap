from __future__ import annotations

import json
from pathlib import Path

from can_diag_console.defs_adapter import build_defs_parser
from diag_defs import DefsEngine


def _write_min_defs(tmp_path: Path) -> Path:
    defs_path = tmp_path / "defs.json"
    defs_path.write_text(
        json.dumps(
            {
                "services": {
                    "0x31": {
                        "name": "StartRoutineByLocalIdentifier",
                        "args": {
                            "default": [
                                {
                                    "name": "routineLocalIdentifier",
                                    "length": 1,
                                    "enum": {"0x02": "clearMemory"},
                                },
                                {"name": "memoryAddress3B", "length": 4},
                                {"name": "memoryType", "length": 1},
                                {"name": "memoryLen", "length": 4},
                                {"name": "raw_payload", "length": -1},
                            ]
                        },
                    },
                    "0x3E": {
                        "name": "TesterPresent",
                        "args": {
                            "default": [
                                {
                                    "name": "responseRequired",
                                    "length": 1,
                                    "enum": {"0x01": "yes"},
                                }
                            ]
                        },
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    return defs_path


def test_defs_engine_prefers_src_tgt_specific_match(tmp_path: Path) -> None:
    defs_path = tmp_path / "defs.json"
    defs_path.write_text(
        json.dumps(
            {
                "services": {
                    "0x50": [
                        {
                            "name": "generic",
                            "args": {"default": [{"name": "status", "length": 1}]},
                        },
                        {
                            "name": "specific",
                            "src": "0x12",
                            "tgt": "0x34",
                            "args": {"default": [{"name": "status", "length": 1}]},
                        },
                    ]
                }
            }
        ),
        encoding="utf-8",
    )

    engine = DefsEngine(str(defs_path))

    service_def, service_name = engine.lookup(0x50, {"src": 0x12, "tgt": 0x34})

    assert service_name == "specific"
    assert service_def is not None
    assert service_def["src"] == "0x12"


def test_defs_engine_decodes_mux_and_raw_payload(tmp_path: Path) -> None:
    defs_path = _write_min_defs(tmp_path)
    engine = DefsEngine(str(defs_path))

    decoded = engine.parse_payload(
        bytes([0x31, 0x02, 0x01, 0x02, 0x03, 0x04, 0x55, 0x00, 0x00, 0x00, 0x10, 0xAA]),
        {"src": 0xF1, "tgt": 0x12, "service_id": 0x31, "service_name": "", "params": {}},
    )

    assert decoded is not None
    assert decoded["service_name"] == "StartRoutineByLocalIdentifier"
    assert decoded["params"]["routineLocalIdentifier"] == {"value": 0x02, "name": "clearMemory"}
    assert decoded["params"]["memoryAddress3B"] == b"\x01\x02\x03\x04"
    assert decoded["params"]["memoryType"] == 0x55
    assert decoded["params"]["memoryLen"] == b"\x00\x00\x00\x10"
    assert decoded["params"]["raw_payload"] == b"\xAA"


def test_build_defs_parser_uses_shared_engine_and_keeps_cdt_alias(tmp_path: Path) -> None:
    defs_path = _write_min_defs(tmp_path)

    parser = build_defs_parser(str(defs_path), cdt_file="ignored.py", provider="cdt")

    assert parser.available is True
    decoded = parser.parse(bytes([0x3E, 0x01]), src=0xF1, tgt=0x12)
    assert decoded is not None
    assert decoded["service_name"] == "TesterPresent"
    assert decoded["params"]["responseRequired"] == {"value": 0x01, "name": "yes"}