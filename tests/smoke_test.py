"""End-to-end checks against the live Supabase project (Milestone 1 tests T1.2).

Run:  python tests/smoke_test.py
Needs .env (see .env.example). Uses the public anon key for every check, exactly
like the website will; the service key is only used to clean up afterwards.
"""

import json
import struct
import sys
import uuid
import zlib
from pathlib import Path
from urllib import error, request

ROOT = Path(__file__).resolve().parent.parent
TEST_PREFIX = "__test__"


def load_env():
    env_path = ROOT / ".env"
    if not env_path.exists():
        sys.exit("Missing .env - copy .env.example to .env and fill it in.")
    env = {}
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    missing = [k for k in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_KEY", "FAMILY_TOKEN")
               if not env.get(k)]
    if missing:
        sys.exit(f"Fill in these values in .env: {', '.join(missing)}")
    return env


ENV = load_env()
BASE = ENV["SUPABASE_URL"].rstrip("/")
ANON = ENV["SUPABASE_ANON_KEY"]
SERVICE = ENV["SUPABASE_SERVICE_KEY"]
TOKEN = ENV["FAMILY_TOKEN"]


def call(method, path, key=ANON, body=None, raw=None, content_type="application/json", headers=None):
    """Return (status, parsed JSON or text). Never raises on HTTP errors."""
    hdrs = {"apikey": key, "Content-Type": content_type}
    if key.startswith("eyJ"):  # legacy JWT keys also go in Authorization; new sb_ keys don't need it
        hdrs["Authorization"] = f"Bearer {key}"
    hdrs.update(headers or {})
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    req = request.Request(BASE + path, data=data, method=method, headers=hdrs)
    try:
        with request.urlopen(req, timeout=30) as resp:
            status, text = resp.status, resp.read().decode(errors="replace")
    except error.HTTPError as e:
        status, text = e.code, e.read().decode(errors="replace")
    try:
        return status, json.loads(text) if text else None
    except json.JSONDecodeError:
        return status, text


def rpc(name, **args):
    return call("POST", f"/rest/v1/rpc/{name}", body=args)


def tiny_png():
    """A valid 1x1 PNG built with the standard library."""
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff")) + chunk(b"IEND", b""))


results = []


def check(label, ok, detail=""):
    ok = bool(ok)
    results.append(ok)
    print(f"  {'PASS' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        -> {detail}"))


def claimed_ids():
    status, body = rpc("get_claims", p_token=TOKEN)
    return {c["jellycat_id"]: c["claimed_by"] for c in body} if status == 200 else None


def is_unclaimed(item_id):
    """True only if get_claims succeeded and the item isn't in it (an empty dict counts)."""
    claims = claimed_ids()
    return claims is not None and item_id not in claims


def run():
    uploaded = []
    print("\nJellycats table (anon key)")
    status, body = call("POST", "/rest/v1/jellycats",
                        body={"name": f"{TEST_PREFIX} Bashful Bunny", "status": "wishlist"},
                        headers={"Prefer": "return=representation"})
    check("insert works", status == 201 and body and body[0].get("id"), f"{status} {body}")
    if status != 201:
        return uploaded
    item_id = body[0]["id"]

    status, body = call("GET", f"/rest/v1/jellycats?id=eq.{item_id}")
    check("select works", status == 200 and len(body) == 1, f"{status} {body}")

    status, body = call("PATCH", f"/rest/v1/jellycats?id=eq.{item_id}", body={"nickname": "Bun"},
                        headers={"Prefer": "return=representation"})
    check("update works", status == 200 and body and body[0]["nickname"] == "Bun", f"{status} {body}")

    call("DELETE", f"/rest/v1/jellycats?id=eq.{item_id}")
    status, body = call("GET", f"/rest/v1/jellycats?id=eq.{item_id}")
    check("hard delete is blocked (soft delete only)", status == 200 and len(body) == 1, f"{status} {body}")

    print("\nSecrets stay hidden (anon key)")
    status, body = call("GET", "/rest/v1/claims")
    check("claims table not directly readable", status >= 400 or body == [], f"{status} {body}")
    status, body = call("GET", "/rest/v1/settings")
    check("settings table not readable", (status >= 400 or body == []) and TOKEN not in json.dumps(body),
          f"{status} {body}")
    status, body = rpc("check_family_token", p_token="wrong")
    check("check_family_token('wrong') is false", status == 200 and body is False, f"{status} {body}")
    status, body = rpc("check_family_token", p_token=TOKEN)
    check("check_family_token(real) is true", status == 200 and body is True, f"{status} {body}")
    status, body = rpc("get_claims", p_token="wrong")
    check("get_claims('wrong') fails", status >= 400, f"{status} {body}")

    print("\nClaims flow")
    check("get_claims(real) works, item unclaimed", (claims := claimed_ids()) is not None and item_id not in claims,
          f"{claims}")
    status, body = rpc("claim_item", p_token="wrong", p_jellycat_id=item_id, p_name="Mom")
    check("claim with wrong token fails", status >= 400, f"{status} {body}")
    status, body = rpc("claim_item", p_token=TOKEN, p_jellycat_id=item_id, p_name="Mom")
    check("claim with real token works", status in (200, 204), f"{status} {body}")
    check("claim shows up as 'Mom'", (claimed_ids() or {}).get(item_id) == "Mom", f"{claimed_ids()}")
    status, body = rpc("claim_item", p_token=TOKEN, p_jellycat_id=item_id, p_name="Aunt Sue")
    check("second claim on same item is rejected", status >= 400, f"{status} {body}")
    status, body = rpc("unclaim_item", p_token=TOKEN, p_jellycat_id=item_id)
    check("unclaim works", status in (200, 204) and is_unclaimed(item_id), f"{status} {body}")

    status, body = rpc("claim_item", p_token=TOKEN, p_jellycat_id=item_id, p_name="   ")
    check("claim with a blank name is rejected", status >= 400 and item_id not in (claimed_ids() or {}),
          f"{status} {body}")

    rpc("claim_item", p_token=TOKEN, p_jellycat_id=item_id, p_name="Mom")
    call("PATCH", f"/rest/v1/jellycats?id=eq.{item_id}", body={"status": "owned"})
    check("marking owned clears the claim (trigger)", is_unclaimed(item_id),
          f"{claimed_ids()}")
    status, body = call("GET", f"/rest/v1/jellycats?id=eq.{item_id}&select=acquired_from")
    check("...and records 'Gift from Mom'", status == 200 and body[0]["acquired_from"] == "Gift from Mom",
          f"{status} {body}")
    status, body = rpc("claim_item", p_token=TOKEN, p_jellycat_id=item_id, p_name="Mom")
    check("owned items can't be claimed", status >= 400, f"{status} {body}")

    print("\nPhoto storage (anon key)")
    path = f"{TEST_PREFIX}/{uuid.uuid4()}.png"
    status, body = call("POST", f"/storage/v1/object/photos/{path}", raw=tiny_png(), content_type="image/png")
    check("small image upload works", status == 200, f"{status} {body}")
    if status == 200:
        uploaded.append(path)
        status, _ = call("GET", f"/storage/v1/object/public/photos/{path}")
        check("public photo URL loads", status == 200, f"{status}")

    big = f"{TEST_PREFIX}/{uuid.uuid4()}.png"
    status, body = call("POST", f"/storage/v1/object/photos/{big}", raw=b"\0" * (3 * 1024 * 1024),
                        content_type="image/png")
    check("3 MB upload is rejected", status >= 400, f"{status} {body}")
    if status == 200:
        uploaded.append(big)

    txt = f"{TEST_PREFIX}/{uuid.uuid4()}.txt"
    status, body = call("POST", f"/storage/v1/object/photos/{txt}", raw=b"hello", content_type="text/plain")
    check("non-image upload is rejected", status >= 400, f"{status} {body}")
    if status == 200:
        uploaded.append(txt)
    return uploaded


def cleanup(uploaded):
    print("\nCleanup (service key)")
    call("DELETE", f"/rest/v1/jellycats?name=like.{TEST_PREFIX}*", key=SERVICE)
    if uploaded:
        call("DELETE", "/storage/v1/object/photos", key=SERVICE, body={"prefixes": uploaded})
    status, body = call("GET", f"/rest/v1/jellycats?name=like.{TEST_PREFIX}*&select=id", key=SERVICE)
    check("no test rows left behind", status == 200 and body == [], f"{status} {body}")


if __name__ == "__main__":
    print(f"Smoke testing {BASE}")
    uploaded = []
    try:
        uploaded = run()
    finally:
        cleanup(uploaded)
    passed = sum(results)
    print(f"\n{passed}/{len(results)} checks passed")
    sys.exit(0 if passed == len(results) else 1)
