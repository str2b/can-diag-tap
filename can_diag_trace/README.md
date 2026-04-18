# CAN Diagnostic Trace

Trace analyzer for offline CAN traces and live capture with protocol decoding and plugins.

It reads CAN traffic, reassembles ISO-TP payloads, decodes configured protocols, and forwards messages to plugin hooks for custom analysis/export.

## Features

- **Multi-Format Traces:** Reads `.asc` and `.blf` trace files.
- **ISOTP Reassembly:** Assembles ISO-TP streams (supports standard and extended addressing).
- **KWP2000 Extraction:** Decodes KWP2000 services with optional custom definitions.
- **UDS Support:** Not implemented yet, but planned.
- **Plugin System:** Extend behavior by loading one or more Python plugin files.

## Arguments

**Source (mutually exclusive, required):**

- `-t`, `--trace <path>`: Path to a trace file (`.asc`, `.blf`, ...)
- `-i`, `--interface <name>`: Live `python-can` interface (for example `pcan`, `socketcan`, `vector`)

**Live Interface Options (only with `--interface`):**

- `-c`, `--channel <channel>`: CAN channel (required for live interface)
- `-b`, `--bitrate <rate>`: Bitrate for the selected interface

**Diagnostic and Decoding:**

- `-a`, `--addressing {standard,extended}`: ISO-TP addressing mode (default: `extended`)
- `-p`, `--protocols {kwp,uds} [...]`: Protocols to decode (default: `kwp`)
- `-d`, `--defs <file.json>`: Custom service definitions
- `-f`, `--filter <file.json>`: Payload filtering rules
- `-pids`, `--physical-ids <id1 id2 ...>`: Arbitration IDs for physical ISO-TP
- `-fids`, `--functional-ids <id1 id2 ...>`: Arbitration IDs for functional ISO-TP

**Extensibility:**

- `-P`, `--plugin <file.py> [file.py ...]`: One or more Python plugin files

## Definitions and Filtering

- `--defs` uses the shared JSON schema from `diag_defs` (see `../diag_defs/README.md`).
- `--filter` uses the shared schema from `diag_filter` (see `../diag_filter/README.md`) and applies during the decode pipeline (`can`, `isotp`, `kwp` layers).

## Quick Start

Use assets from `../examples/`:

```sh
can-diag-trace -t ../examples/smoke_test.asc -f ../examples/filter_demo.json -d ../examples/kwp_defs_demo.json -P ../plugins/trace_printer.py --print can isotp kwp
```

## Quick Dev Intro

```sh
cd can_diag_trace
python -m venv .venv
# activate the virtual environment in your shell
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Developer Notes

This section is for extending the tracer (plugins/decoders), not for normal usage.

Plugin hooks (all optional):

- `add_arguments(parser)`
- `init(args)`
- `on_can_message(can_frame)`
- `on_isotp_message(isotp_msg)`
- `on_kwp_message(kwp_msg)`
- `teardown()`

Core extension points:

- `ProtocolRegistry`: register additional protocol decoders
- `PluginRegistry`: fan-out decoded messages to loaded plugins
- `TraceAnalyzer`: orchestrates source -> CAN -> ISOTP -> protocol -> plugins

Workspace plugin examples:

- `../plugins/trace_printer.py`
- `../plugins/srec_dumper.py`
