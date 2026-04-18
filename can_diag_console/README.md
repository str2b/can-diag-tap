# CAN Diagnostic Console

Standalone Python project for interactive CAN diagnostics.

It opens a CAN diagnostic session, lets you send requests from an interactive console (or one-shot CLI run), and shows decoded responses in a workflow suited to bring-up and troubleshooting.

It supports:

- Sending raw diagnostic bytes
- Receiving asynchronous responses
- Protocol modes: `kwp2000`, `uds`
- Optional parsing of diagnostic definitions JSON via shared `diag_defs.DefsEngine`
- Optional payload filtering via `--filter` (shared `diag_filter` rules)
- Adapter boundary for backend extensibility (`python-can`, `kdcan` hook)
- `gs_usb` discovery helper with auto-channel selection

Definitions and filtering references:

- Definitions schema: `../diag_defs/README.md`
- Filter schema: `../diag_filter/README.md`

## User Documentation

Quick start:

```sh
can-diag-console --interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --protocol uds --tx-id 0x6F1 --rx-id 0x615 --defs ../examples/kwp_defs_demo.json
```

`gs_usb` with auto channel:

```sh
can-diag-console --adapter python-can --interface gs_usb --bitrate 500000 --protocol uds --tx-id 0x6F1 --rx-id 0x615 --defs ../examples/kwp_defs_demo.json
```

Filtering is optional and uses the same JSON format as the tracer:

```sh
can-diag-console --interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --protocol uds --tx-id 0x6F1 --rx-id 0x615 --defs ../examples/kwp_defs_demo.json --filter ../examples/filter_demo.json
```

If `--source-addr`/`--target-addr` are omitted in extended mode, defaults are derived from ID low bytes:
- `source-addr = tx-id & 0xFF`
- `target-addr = rx-id & 0xFF`

If your firmware/runtime reports HW timestamps but python-can shows frame unpack errors,
HW timestamps are disabled by default for gs_usb in this project.
You can override with:

```sh
can-diag-console --adapter python-can --interface gs_usb --adapter-options '{"disable_hw_timestamps": false}' --protocol uds --tx-id 0x6F1 --rx-id 0x612
```

Interactive usage:

- Enter raw bytes: `10 81`, `0x10 0x81`, or `1081`
- Output formatting is trace-oriented and defs-aware for both TX and RX lines:
  - `[timestamp] DIR [src->tgt | length] [service | decoded params]`
- Built-in commands:
  - `:help`
  - `:quit`
  - `:businfo`
  - `:kwp <hex bytes>`
  - `:kwp-tp <on|off|status|toggle> [interval_s] [hex bytes]`
  - `:kwp-rmem <start> <end> [chunk=0xF0] [type=0x00] [timeout=1.0] [srec=<path>]`
  - `:proto kwp2000|uds`
  - `:tx 0x6F1`
  - `:rx 0x615`
  - `:defs <path>`
  - `:nodefs`

Notes:

- For `kwp2000` and `uds`, transport is ISO-TP (`can-isotp`).
- `--adapter kdcan` currently exposes the extension boundary but requires wiring your concrete K/DCAN backend driver in `adapters.py`.
- If `--channel` is omitted with `--adapter python-can --interface gs_usb`, the first detected gs_usb channel is used.

### Windows driver note for gs_usb

- Keep the device bound to `WinUSB` in Device Manager/Zadig.
- In addition, python `gs_usb` needs a userspace `libusb` DLL. This project now includes `libusb-package` and auto-wires it at runtime.

## Quick Dev Intro

```sh
cd can_diag_console
python -m venv .venv
# activate the virtual environment in your shell
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Programmer Interface

You can use the package directly from Python applications without the interactive shell.

```python
from can_diag_console import DiagClient, DiagClientConfig

cfg = DiagClientConfig(
  adapter="python-can",
  interface="gs_usb",
  bitrate=500000,
  protocol="kwp2000",
  tx_id=0x6F1,
  rx_id=0x612,
  isotp_addressing="extended",
  defs="../examples/kwp_defs_demo.json",
)

with DiagClient(cfg) as client:
  # one-shot request/response
  response = client.request("3E 01", timeout=2.0)
  print("response:", response)

  # periodic tester present while your app does other work
  client.start_tester_present(interval=2.0, payload="3E 00")
  # ... application logic ...
  client.stop_tester_present()
```

Main API methods:

- `open()` / `close()` (or context manager)
- `send(bytes|str)`
- `recv(timeout)`
- `request(bytes|str, timeout)`
- `decode(payload)` (when defs are configured)
- `start_tester_present(interval, payload)` / `stop_tester_present()`
- `read_memory(start, end, chunk_size=0xF0, memory_type=0x00, timeout=1.0, srec_path=None)`

Read memory helper notes:

- Splits reads into chunked requests (`0x23`), default chunk `0xF0`
- If negative response occurs, recursively splits (binary-search style) to isolate protected addresses
- Continues reading other addresses and optionally exports readable chunks to SREC using `hexrec`

Example command:

```text
:kwp-rmem 0x80000000 0x80000EFF chunk=0xF0 timeout=1.0 srec=./dump/live.srec
```
