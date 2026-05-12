# CAN Diagnostic Console

Standalone Python project for interactive CAN diagnostics.

It opens a CAN diagnostic session, lets you send requests from an interactive console (or one-shot CLI run), and shows decoded responses in a workflow suited to bring-up and troubleshooting.

It supports:

- Sending raw diagnostic bytes
- Receiving asynchronous responses
- Optional parsing of diagnostic definitions JSON via shared `diag_defs.DefsEngine`
- Optional payload filtering via `--filter` (shared `diag_filter` rules)
- Adapter boundary for backend extensibility (`python-can`, `kdcan` hook)
- `gs_usb` discovery helper with auto-channel selection

Definitions and filtering references:

- Definitions schema: `../diag_defs/README.md`
- Filter schema: `../diag_filter/README.md`

## User Documentation

### CLI Arguments

| Argument | Default | Description |
|---|---|---|
| `--tx-id` | *(required)* | Tester-to-ECU CAN frame ID |
| `--rx-id` | *(required)* | ECU-to-Tester CAN frame ID |
| `--adapter` | `python-can` | Hardware adapter backend (`python-can`, `kdcan`) |
| `--interface` | `gs_usb` | python-can interface (e.g. `gs_usb`, `pcan`, `vector`, `socketcan`) |
| `--channel` | *(auto for gs_usb)* | Interface channel (e.g. `0`, `PCAN_USBBUS1`, `can0`) |
| `--bitrate` | `500000` | CAN bitrate in bit/s |
| `--isotp-addressing` | `extended` | ISO-TP addressing mode (`normal` or `extended`) |
| `--source-addr` | low byte of `--tx-id` | ISO-TP extended-address source byte |
| `--target-addr` | low byte of `--rx-id` | ISO-TP extended-address target byte |
| `--defs` | | Path to JSON diagnostic definitions file (`diag_defs`-compatible) |
| `--filter` | | Path to JSON filter file (`diag_filter`-compatible) |
| `--run CMD [CMD ...]` | | Run one or more commands non-interactively and exit |
| `--adapter-options` | | JSON object with adapter-specific settings |
| `--adapter-plugin` | | Adapter plugin module/path (repeatable); must export `register_adapters(register_adapter)` |
| `--command-plugin` | | Command plugin module/path (repeatable); must export `register_commands(processor)` |

### Quick Start

```sh
can-diag-console --interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --tx-id 0x6F1 --rx-id 0x615 --defs ../examples/kwp_defs_demo.json
```

`gs_usb` with auto channel:

```sh
can-diag-console --adapter python-can --interface gs_usb --bitrate 500000 --tx-id 0x6F1 --rx-id 0x615 --defs ../examples/kwp_defs_demo.json
```

Filtering is optional and uses the same JSON format as the tracer:

```sh
can-diag-console --interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --tx-id 0x6F1 --rx-id 0x615 --defs ../examples/kwp_defs_demo.json --filter ../examples/filter_demo.json
```

If `--source-addr`/`--target-addr` are omitted in extended mode, defaults are derived from ID low bytes:
- `source-addr = tx-id & 0xFF`
- `target-addr = rx-id & 0xFF`

If your firmware/runtime reports HW timestamps but python-can shows frame unpack errors,
HW timestamps are disabled by default for gs_usb in this project.
You can override with:

```sh
can-diag-console --adapter python-can --interface gs_usb --adapter-options '{"disable_hw_timestamps": false}' --tx-id 0x6F1 --rx-id 0x612
```

### Interactive Commands

- Input is command-driven; all actions must start with `:`
- Output formatting is trace-oriented and defs-aware for both TX and RX lines:
  - `[timestamp] DIR [src->tgt | length] [service | decoded params]`

Built-in commands:

**General:**

| Command | Description |
|---|---|
| `:help` | Show available commands |
| `:quit` | Exit the console |
| `:businfo` | Print CAN bus and adapter info |
| `:tx <id>` | Change the TX CAN ID |
| `:rx <id>` | Change the RX CAN ID |
| `:defs <path>` | Load a diagnostic definitions JSON |
| `:nodefs` | Unload the current definitions |
| `:raw <hex bytes>` (alias `:tp`) | Send a raw ISO-TP payload bytes |

**Supported KWP commands:**

| Command | KWP service | Description |
|---|---|---|
| `:kwp-diag-session <default\|programming\|extended> [timeout=1.0]` | `0x10` | Start diagnostic session |
| `:kwp-tp <on\|off\|status\|toggle> [interval_s] [hex bytes]` | `0x3E` | Manage periodic tester present |
| `:kwp-memread <start> <end> [chunk=0xF0] [type=0x00] [timeout=1.0] [srec=<path>]` (aliases `:memread`, `:rmem`, `:kwp-rmem`) | `0x23` | Bulk-read ECU memory range |
| `:kwp-auth-sk [seed1=43444331] [retries=3] [delay=2.0] [timeout=2.0] [keyscript=<path>]` | OEM routine flow | Full KWP seed-key authentication flow |

#### :kwp-memread

Reads ECU memory using KWP2000 `ReadMemoryByAddress` (`0x23`):

- Splits the address range into chunks (default `0xF0` bytes per request)
- If a negative response is received, recursively bisects the range to isolate unreadable addresses
- Continues reading remaining addresses; optionally exports all readable chunks to SREC using `hexrec`

Example:

```text
:kwp-memread 0x80000000 0x80000EFF chunk=0xF0 timeout=1.0 srec=./dump/live.srec
```

#### :kwp-auth-sk

Runs a KWP seed-key authentication flow:

- Reads ECU serial via `1A 89`
- Computes and prints seed values:
  - `seed1`: challenge request seed (default `43 44 43 31`, overridable via `seed1=<hex>`)
  - `seed2`: last 4 bytes from ECU identification response (`1A 89` response)
  - `seed3`: challenge bytes returned from `31 07`
- Requests auth challenge via `31 07 03 <seed1>`
- Asks user for externally computed key payload based on the received challenge
  - At the key prompt, type `abort`, `cancel`, `:q`, `:quit`, `:exit` (or press `Ctrl+C`) to return to command entry
- Optional automation via `keyscript=<path>` (script is called with `--s1/--s2/--s3` hex seeds and prints key hex)
- Sends release authentication via `31 08 00 00 00 10 <key-payload>` (with retry support)

### Notes

- Transport uses ISO-TP (`can-isotp`).
- `--adapter kdcan` currently exposes the extension boundary but requires wiring your concrete K/DCAN backend driver in `adapters.py`.
- If `--channel` is omitted with `--adapter python-can --interface gs_usb`, the first detected gs_usb channel is used.

### Windows Driver Note for gs_usb

- Keep the device bound to `WinUSB` in Device Manager/Zadig.
- Python `gs_usb` needs a userspace `libusb` DLL. This project includes `libusb-package` and auto-wires it at runtime.

## Development Setup

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
