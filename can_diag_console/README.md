# CAN Diagnostic Console

Standalone Python project for interactive CAN diagnostics.

It supports:
- Sending raw diagnostic bytes
- Receiving asynchronous responses
- Protocol modes: `kwp2000`, `uds`
- Optional parsing of diagnostic definitions JSON via shared `diag_defs.DefsEngine`
- Adapter boundary for backend extensibility (`python-can`, `kdcan` hook)
- `gs_usb` discovery helper with auto-channel selection

## Architecture (Separation of Concerns)

- `console.py`: interactive shell only (stdin loop + output)
- `session.py`: runtime orchestration (adapter, transport, RX worker, tester-present worker)
- `commands.py`: command parser/executor (`:kwp`, `:kwp-tp`, bus/defs/protocol controls)
- `adapters.py`: hardware backend abstraction and lifecycle
- `transport.py`: protocol transport behavior over an open bus
- `defs_adapter.py`: adapter over shared `diag_defs.DefsEngine` for JSON decoding
- `protocols.py`: protocol enums + shared byte parsing helpers

This means adding a new hardware backend (for example a concrete BMW K/DCAN driver)
requires changes in `adapters.py` only, while console and protocol logic remain untouched.

## Workspace Role

`can_diag_console` is a peer package in this workspace alongside:
- `can_diag_trace/` for trace analysis
- `diag_defs/` for shared definitions parsing

For local development, `requirements.txt` installs `diag_defs` in editable mode.

## Setup (Windows PowerShell)

```powershell
cd can_diag_console
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Run

Example (UDS / ISO-TP):

```powershell
can-diag-console --interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --protocol uds --tx-id 0x6F1 --rx-id 0x615 --defs ..\test_input\kwp_defs.json
```

Example (candleLight / gs_usb with auto channel):

```powershell
can-diag-console --adapter python-can --interface gs_usb --bitrate 500000 --protocol uds --tx-id 0x6F1 --rx-id 0x615 --defs ..\test_input\kwp_defs.json
```

BMW KWP scheme from trace files (extended ISO-TP, source/target byte addressing):

```powershell
can-diag-console --adapter python-can --interface gs_usb --bitrate 500000 --protocol kwp2000 --tx-id 0x6F1 --rx-id 0x612 --isotp-addressing extended --defs ..\test_input\kwp_defs.json
```

If `--source-addr`/`--target-addr` are omitted in extended mode, defaults are derived from ID low bytes:
- `source-addr = tx-id & 0xFF`
- `target-addr = rx-id & 0xFF`

Select a specific gs_usb serial (via adapter options JSON):

```powershell
can-diag-console --adapter python-can --interface gs_usb --adapter-options '{"serial":"123456"}' --protocol uds --tx-id 0x6F1 --rx-id 0x615
```

If your firmware/runtime reports HW timestamps but python-can shows frame unpack errors,
HW timestamps are disabled by default for gs_usb in this project.
You can override with:

```powershell
can-diag-console --adapter python-can --interface gs_usb --adapter-options '{"disable_hw_timestamps": false}' --protocol uds --tx-id 0x6F1 --rx-id 0x612
```

Explicit adapter selection:

```powershell
can-diag-console --adapter python-can --interface pcan --channel PCAN_USBBUS1 --bitrate 500000 --protocol kwp2000 --tx-id 0x6F1 --rx-id 0x615
```

## Console Usage

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
    defs="../test_input/kwp_defs.json",
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

  ### Read Memory Command

  `ReadMemoryByAddress` helper supports long-range reads with split/recovery logic:

  - Splits reads into chunked requests (`0x23`), default chunk `0xF0`
  - If negative response occurs, recursively splits (binary-search style) to isolate protected addresses
  - Continues reading other addresses and optionally exports readable chunks to SREC using `hexrec`

  Example:

  ```text
  :kwp-rmem 0x8000084C 0x8001084C chunk=0xF0 type=0x00 timeout=0.8 srec=./dump/read_8000084C_8001084C.srec
  ```

  Progress mode suppresses per-frame TX/RX lines during dump and prints only progress + summary.
  It is enabled automatically when `srec=<path>` is set:

  ```text
  :kwp-rmem 0x80000000 0x80000EFF chunk=0xF0 timeout=1.0 srec=./dump/live.srec
  ```

## Shared Definitions

`can_diag_console` uses the shared `diag_defs` parser that is also consumed by `can-diag-trace`.

The deprecated `--cdt-file` and `--defs-provider cdt` options are still accepted for compatibility,
but defs parsing no longer depends on loading `cdt.py` from the repo layout.

## Notes

- For `kwp2000` and `uds`, transport is ISO-TP (`can-isotp`).
- `--adapter kdcan` currently exposes the extension boundary but requires wiring your concrete K/DCAN backend driver in `adapters.py`.
- If `--channel` is omitted with `--adapter python-can --interface gs_usb`, the first detected gs_usb channel is used.

### Windows driver note for gs_usb

- Keep the device bound to `WinUSB` in Device Manager/Zadig.
- In addition, python `gs_usb` needs a userspace `libusb` DLL. This project now includes `libusb-package` and auto-wires it at runtime.
