from __future__ import annotations

import argparse
import sys

from .adapters import register_adapter
from .console import DiagnosticConsole
from .extensions import load_adapter_plugins
from .protocols import DiagProtocol


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Interactive CAN diagnostic console for KWP2000 / UDS"
    )
    parser.add_argument(
        "--adapter",
        default="python-can",
        help="Hardware adapter backend name (default: python-can)",
    )
    parser.add_argument(
        "--adapter-plugin",
        action="append",
        default=[],
        help="Optional adapter plugin module/path. Must export register_adapters(register_adapter).",
    )
    parser.add_argument(
        "--command-plugin",
        action="append",
        default=[],
        help="Optional command plugin module/path. Must export register_commands(processor).",
    )
    parser.add_argument(
        "--interface",
        default="gs_usb",
        help="python-can interface (e.g. gs_usb, pcan, vector, socketcan)",
    )
    parser.add_argument(
        "--channel",
        help="Interface channel (e.g. 0 for gs_usb, PCAN_USBBUS1, can0). Optional for gs_usb auto-detect.",
    )
    parser.add_argument("--bitrate", type=int, default=500000, help="CAN bitrate (default: 500000)")
    parser.add_argument(
        "--adapter-options",
        help="Optional JSON object with adapter-specific settings for future backends",
    )
    parser.add_argument("--protocol", choices=[p.value for p in DiagProtocol], default=DiagProtocol.UDS.value)
    parser.add_argument("--tx-id", type=lambda x: int(x, 0), help="Tester-to-ECU CAN frame ID")
    parser.add_argument("--rx-id", type=lambda x: int(x, 0), help="ECU-to-Tester CAN frame ID")
    parser.add_argument(
        "--isotp-addressing",
        choices=["normal", "extended"],
        default="extended",
        help="ISO-TP addressing mode (default: extended, common for KWP setups)",
    )
    parser.add_argument(
        "--source-addr",
        type=lambda x: int(x, 0),
        help="ISO-TP extended-address source byte (layer above CAN ID; default: low byte of tx-id)",
    )
    parser.add_argument(
        "--target-addr",
        type=lambda x: int(x, 0),
        help="ISO-TP extended-address target byte (layer above CAN ID; default: low byte of rx-id)",
    )
    parser.add_argument("--defs", help="Path to diag_defs-compatible JSON definitions")
    parser.add_argument(
        "--cdt-file",
        help="Deprecated compatibility option. Ignored now that defs parsing is provided by diag_defs.",
    )
    parser.add_argument(
        "--defs-provider",
        choices=["auto", "cdt", "none"],
        default="auto",
        help="Defs parsing provider: auto, none, or deprecated compatibility alias cdt.",
    )
    parser.add_argument(
        "--filter",
        help="Optional JSON filter configuration (same format as can-diag-trace).",
    )
    parser.add_argument(
        "--run",
        metavar="CMD",
        nargs="+",
        help="Run one or more commands non-interactively and exit (e.g. --run ':kwp 3E 01')",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()

    if args.adapter_plugin:
        load_adapter_plugins(args.adapter_plugin, register_adapter)

    if args.tx_id is None or args.rx_id is None:
        raise SystemExit("--tx-id and --rx-id are required.")

    if args.source_addr is None:
        args.source_addr = args.tx_id & 0xFF
    if args.target_addr is None:
        args.target_addr = args.rx_id & 0xFF

    if args.adapter == "python-can" and args.channel is None and args.interface != "gs_usb":
        raise SystemExit("--channel is required for --adapter python-can unless --interface gs_usb is used.")

    if args.run:
        sys.exit(DiagnosticConsole(args).run_commands(args.run))
    sys.exit(DiagnosticConsole(args).run())


if __name__ == "__main__":
    main()
