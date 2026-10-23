"""Add sample Jellycats for trying out the website (Milestone 2, step 2.2).

Run:  python tests/seed.py           add 8 samples (some with photos)
      python tests/seed.py --clear   remove them again

The ids of the rows it adds are kept in tests/.seeded.json, so --clear only ever
removes sample data, never real Jellycats. Uses the service key from .env.
"""

import json
import struct
import sys
import uuid
import zlib
from pathlib import Path

from smoke_test import SERVICE, call

SEEDED = Path(__file__).resolve().parent / ".seeded.json"

# (name, nickname, size, category, status, acquired_date, acquired_from, notes, photo colour or None)
SAMPLES = [
    ("Bashful Bunny", "Bun", "Medium", "Bunnies", "owned", "2024-12-25", "Gift from Mom",
     "The very first one. Sleeps on the bed.", (236, 222, 205)),
    ("Amuseable Avocado", "Avo", "Small", "Amuseables", "owned", "2025-03-14", "Selfridges",
     None, (170, 196, 120)),
    ("Fuddlewuddle Lion", None, "Medium", "Animals", "owned", "2025-06-02", "Airport shop",
     "Fluffiest mane ever.", None),
    ("Bartholomew Bear", "Barty", "Large", "Bears", "owned", "2025-08-19", "Gift from Trevor",
     None, (160, 120, 90)),
    ("Blossom Tulip Bunny", None, "Small", "Bunnies", "owned", "2026-02-14", "Valentine's Day",
     None, None),
    ("Amuseable Croissant", None, "Small", "Amuseables", "wishlist", None, None,
     "The one with the little smile.", (230, 180, 100)),
    ("Smudge Elephant", None, "Medium", "Animals", "wishlist", None, None, None, None),
    ("Bashful Luxe Bunny Luna", None, "Huge", "Bunnies", "wishlist", None, None,
     "Seen at the store downtown.", (215, 215, 225)),
]


def png(rgb, width=300, height=400):
    """A plain-coloured PNG, taller than wide so the 'fit inside the tile' look is visible."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    row = b"\x00" + bytes(rgb) * width
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(row * height)) + chunk(b"IEND", b""))


def load_seeded():
    return json.loads(SEEDED.read_text()) if SEEDED.exists() else {"ids": [], "photos": []}


def seed():
    seeded = load_seeded()
    if seeded["ids"]:
        sys.exit("Samples already added. Run with --clear first.")
    for name, nickname, size, category, status, acquired, source, notes, colour in SAMPLES:
        photo_path = None
        if colour:
            photo_path = f"seed/{uuid.uuid4()}.png"
            code, body = call("POST", f"/storage/v1/object/photos/{photo_path}", key=SERVICE,
                              raw=png(colour), content_type="image/png")
            if code != 200:
                sys.exit(f"Photo upload failed for {name}: {code} {body}")
            seeded["photos"].append(photo_path)
        row = {"name": name, "nickname": nickname, "size": size, "category": category, "status": status,
               "acquired_date": acquired, "acquired_from": source, "notes": notes, "photo_path": photo_path}
        code, body = call("POST", "/rest/v1/jellycats", key=SERVICE, body=row,
                          headers={"Prefer": "return=representation"})
        if code != 201:
            SEEDED.write_text(json.dumps(seeded))
            sys.exit(f"Insert failed for {name}: {code} {body}")
        seeded["ids"].append(body[0]["id"])
        print(f"  added  {name}" + ("" if colour else "  (no photo)"))
    SEEDED.write_text(json.dumps(seeded))
    print(f"{len(seeded['ids'])} samples added.")


def clear():
    seeded = load_seeded()
    if not seeded["ids"] and not seeded["photos"]:
        print("No samples to remove.")
        return
    if seeded["ids"]:
        code, body = call("DELETE", f"/rest/v1/jellycats?id=in.({','.join(seeded['ids'])})", key=SERVICE)
        if code not in (200, 204):
            sys.exit(f"Delete failed: {code} {body}")
    if seeded["photos"]:
        code, body = call("DELETE", "/storage/v1/object/photos", key=SERVICE, body={"prefixes": seeded["photos"]})
        if code != 200:
            sys.exit(f"Photo delete failed: {code} {body}")
    SEEDED.unlink()
    print(f"Removed {len(seeded['ids'])} samples and {len(seeded['photos'])} photos.")


if __name__ == "__main__":
    clear() if "--clear" in sys.argv else seed()
