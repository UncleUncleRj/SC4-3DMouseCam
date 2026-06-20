"""Build the dependency-free SC4 DBPF file containing our UI script."""

from pathlib import Path
import struct
import sys
import time


TYPE_ID = 0x00000000
GROUP_ID = 0x3D0C0700
INSTANCE_ID = 0x3D0C0701
HEADER_SIZE = 96


def build(source: Path, destination: Path) -> None:
    payload = source.read_bytes()
    index_offset = HEADER_SIZE + len(payload)
    header = bytearray(HEADER_SIZE)
    header[0:4] = b"DBPF"
    struct.pack_into("<II", header, 4, 1, 0)
    now = int(time.time())
    struct.pack_into("<II", header, 0x18, now, now)
    struct.pack_into("<IIII", header, 0x20, 7, 1, index_offset, 20)
    struct.pack_into("<III", header, 0x30, 0, 0, 0)
    struct.pack_into("<I", header, 0x3C, 0)
    index = struct.pack("<IIIII", TYPE_ID, GROUP_ID, INSTANCE_ID, HEADER_SIZE, len(payload))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(header + payload + index)
    print(f"Wrote {destination} ({destination.stat().st_size} bytes)")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: build_sc4_ui_dat.py SOURCE DESTINATION")
    build(Path(sys.argv[1]), Path(sys.argv[2]))
