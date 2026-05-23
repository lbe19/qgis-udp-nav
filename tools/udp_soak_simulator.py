from __future__ import annotations

import argparse
import socket
import sys
import time

from qgis_udp_nav_plugin.parser.core import calculate_checksum


def _sentence(body: str) -> str:
    return f"${body}*{calculate_checksum(body)}"


def _hhmmss(day_minute: int) -> str:
    hour = (int(day_minute) // 60) % 24
    minute = int(day_minute) % 60
    second = 0
    return f"{hour:02d}{minute:02d}{second:02d}.00"


def _datagram_for_virtual_minute(minute_index: int) -> str:
    day_minute = minute_index % (24 * 60)
    clock = _hhmmss(day_minute)

    lines: list[str] = [
        _sentence(
            f"GPGGA,{clock},7002.968962,N,02938.350607,E,2,12,0.6,-0.52,M,20.34,M,7.0,0907"
        ),
        _sentence(f"GPGLL,7002.968962,N,02938.350607,E,{clock},A,D"),
    ]

    if day_minute < 180:
        pos_item = ""
    elif day_minute < 720:
        pos_item = "42"
        error_code = "NRy" if (minute_index % 11) == 0 else ""
        x_value = 46.0 + ((minute_index // 1) % 10) * 0.1
        y_value = 1.5 + ((minute_index // 1) % 5) * 0.01
        depth_m = 24.0 + ((minute_index // 1) % 7) * 0.5
        lines.append(
            _sentence(
                "PSIMSSB,"
                f"{clock},M17,A,{error_code},C,N,F,"
                f"{x_value:.3f},{y_value:.3f},{depth_m:.3f},1.414,T,0.033681,"
            )
        )
    else:
        pos_item = ""
        if (minute_index % 3) == 0:
            lines.append(
                _sentence(f"PSIMSSB,{clock},M17,V,NRy,C,N,M,,,,,T,0.002245,")
            )

    lines.append(
        _sentence(
            "PSIMSNS,"
            f"{clock},{pos_item},1,1,-1.27,-1.13,-0.04,250.87,,a0,0.000,,M121"
        )
    )

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Replay a synthetic multi-phase vessel/vehicle workflow over UDP for soak testing "
            "QGIS UDP Nav in a live QGIS session."
        )
    )
    parser.add_argument("--host", default="127.0.0.1", help="Target host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=10110, help="Target UDP port (default: 10110)")
    parser.add_argument(
        "--virtual-days",
        type=int,
        default=7,
        help="How many virtual days to replay (default: 7)",
    )
    parser.add_argument(
        "--minute-step",
        type=int,
        default=1,
        help="Virtual minute step per packet batch (default: 1)",
    )
    parser.add_argument(
        "--speedup",
        type=float,
        default=120.0,
        help=(
            "Virtual-to-real-time speedup factor (default: 120). "
            "At 120x, 7 virtual days complete in about 84 real minutes."
        ),
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=500,
        help="Print progress every N datagrams (default: 500)",
    )

    args = parser.parse_args()

    if args.port <= 0 or args.port > 65535:
        print("Invalid --port, expected 1..65535", file=sys.stderr)
        return 2
    if args.virtual_days <= 0:
        print("Invalid --virtual-days, expected > 0", file=sys.stderr)
        return 2
    if args.minute_step <= 0:
        print("Invalid --minute-step, expected > 0", file=sys.stderr)
        return 2
    if args.speedup <= 0:
        print("Invalid --speedup, expected > 0", file=sys.stderr)
        return 2

    total_virtual_minutes = args.virtual_days * 24 * 60
    minute_indices = list(range(0, total_virtual_minutes, args.minute_step))
    total_datagrams = len(minute_indices)
    sleep_seconds = (args.minute_step * 60.0) / args.speedup

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

    print(
        "Starting UDP soak replay: "
        f"target={args.host}:{args.port}, virtual_days={args.virtual_days}, "
        f"minute_step={args.minute_step}, speedup={args.speedup}x, "
        f"datagrams={total_datagrams}, sleep={sleep_seconds:.4f}s"
    )

    started = time.monotonic()
    try:
        for index, minute_index in enumerate(minute_indices, start=1):
            payload = _datagram_for_virtual_minute(minute_index)
            sock.sendto(payload.encode("ascii", errors="replace"), (args.host, args.port))

            if args.progress_every > 0 and (index % args.progress_every) == 0:
                elapsed = max(0.001, time.monotonic() - started)
                rate = index / elapsed
                print(
                    f"Progress: {index}/{total_datagrams} datagrams sent "
                    f"({rate:.1f} datagrams/s)"
                )

            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
    finally:
        sock.close()

    elapsed = time.monotonic() - started
    print(f"Completed soak replay in {elapsed:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
