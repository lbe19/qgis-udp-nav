"""
Simple UDP NMEA sender for testing the QGIS UDP Nav Plugin.

Run this script while QGIS is open with the plugin active.
It sends a valid GGA sentence every second to localhost:10110.
If the plugin is working, you should see a marker appear on the map near Oslo.

Usage:
    python tools/udp_test_sender.py [port]
"""
import socket
import sys
import time
from datetime import datetime, timezone


def make_gga(lat: float, lon: float) -> str:
    """Create a valid NMEA GGA sentence with checksum."""
    now = datetime.now(timezone.utc)
    time_str = now.strftime("%H%M%S.00")

    lat_deg = int(abs(lat))
    lat_min = (abs(lat) - lat_deg) * 60
    lat_str = f"{lat_deg:02d}{lat_min:07.4f}"
    lat_ns = "N" if lat >= 0 else "S"

    lon_deg = int(abs(lon))
    lon_min = (abs(lon) - lon_deg) * 60
    lon_str = f"{lon_deg:03d}{lon_min:07.4f}"
    lon_ew = "E" if lon >= 0 else "W"

    body = f"GPGGA,{time_str},{lat_str},{lat_ns},{lon_str},{lon_ew},1,08,0.9,25.0,M,0.0,M,,"
    checksum = 0
    for ch in body:
        checksum ^= ord(ch)
    return f"${body}*{checksum:02X}\r\n"


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 10110
    host = "127.0.0.1"

    # Oslo coordinates
    lat, lon = 59.9139, 10.7522

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    print(f"Sending NMEA GGA to {host}:{port} every 1 second...")
    print(f"Position: {lat}, {lon} (Oslo)")
    print("Press Ctrl+C to stop.\n")

    count = 0
    try:
        while True:
            sentence = make_gga(lat, lon)
            sock.sendto(sentence.encode("ascii"), (host, port))
            count += 1
            print(f"  [{count}] Sent: {sentence.strip()}")
            time.sleep(1.0)
    except KeyboardInterrupt:
        print(f"\nStopped after {count} sentences.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
