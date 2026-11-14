#!/usr/bin/env python3
"""falrec.py — read fal's own record back out of a generated clip.

Every fal output carries a C2PA Content Credentials manifest, and its
`ai.fal.info` assertion holds the `request_id`. That id is the key to the whole
generation record at the ACCOUNT endpoint (a different surface from the model
result endpoint):

    https://rest.alpha.fal.ai/requests/{id}
      json_input      the ORIGINAL prompt and every parameter
      json_output     includes expanded_prompt
      called_endpoint, cost, billable_units, timings, billing_status

So a file is self-describing: no naming discipline is required to know what a
clip is, which prompt made it, or what it cost. Shared by `ingest.py` (file it
and author the card from the record) and `fal-recover.py` (backfill a batch).

Known limits: ids in the newer `v1-` form are rejected by the account endpoint
(422 uuid_parsing) and return "Request not found" from the queue endpoint, so
those clips need their prompt from wherever it was written. `cost` and
`billing_status` can stay null/PENDING long after a run, so never report spend
from them without checking.
"""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

RECORD = "https://rest.alpha.fal.ai/requests/{}"
_ID_UUID = re.compile(
    rb"request_id.{0,4}([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.S)
_ID_V1 = re.compile(rb"request_id.{0,4}(v1-[A-Za-z0-9_+/=-]{16,})", re.S)
SIDECAR = ".fal.json"
EXPANDED = ".expanded.txt"


class NoRecord(Exception):
    """No usable fal request id in the file (found media, or a v1- id)."""


def load_key() -> str:
    key = os.environ.get("FAL_KEY")
    if not key:
        raise NoRecord("FAL_KEY is not set (export it in your shell; it is read from the environment only)")
    return key


def extract_request_id(path: Path) -> str | None:
    raw = Path(path).open("rb").read()
    m = _ID_UUID.search(raw) or _ID_V1.search(raw)
    return m.group(1).decode() if m else None


def fetch(req_id: str, key: str) -> dict:
    url = RECORD.format(urllib.parse.quote(req_id, safe=""))
    req = urllib.request.Request(url, headers={"Authorization": f"Key {key}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def sidecar_for(clip: Path) -> Path:
    return Path(clip).with_suffix(SIDECAR)


def recover(clip: Path, key: str | None = None, refresh: bool = False) -> dict | None:
    """The fal record for a clip, cached beside it as `<clip>.fal.json`.

    Returns None when the clip has no fal id at all (found media). Raises on a
    fetch failure so a caller can tell "not ours" from "could not reach fal".
    """
    clip = Path(clip)
    cache = sidecar_for(clip)
    if cache.is_file() and not refresh:
        return json.loads(cache.read_text())
    rid = extract_request_id(clip)
    if rid is None:
        return None
    rec = fetch(rid, key or load_key())
    cache.write_text(json.dumps(rec, indent=1))
    exp = (rec.get("json_output") or {}).get("expanded_prompt")
    if exp:
        clip.with_suffix(EXPANDED).write_text(exp + "\n")
    return rec


def prompt_of(rec: dict | None) -> str:
    """The prompt as actually sent to fal."""
    return ((rec or {}).get("json_input") or {}).get("prompt", "").strip()


def expanded_of(rec: dict | None) -> str:
    return ((rec or {}).get("json_output") or {}).get("expanded_prompt", "") or ""


def summary(rec: dict | None) -> dict:
    inp = (rec or {}).get("json_input") or {}
    return {
        "endpoint": (rec or {}).get("called_endpoint") or (rec or {}).get("endpoint"),
        "duration": inp.get("duration"),
        "resolution": inp.get("resolution"),
        "expansion": inp.get("prompt_expansion_mode"),
        "image_url": bool(inp.get("image_url")),
        "billing_status": (rec or {}).get("billing_status"),
        "request_id": (rec or {}).get("request_id"),
        "queued_at": (rec or {}).get("queued_at"),
    }


def alt_from_expanded(rec: dict | None, limit: int = 150) -> str:
    """A first-draft alt text from the model's own description of the shot.

    Machine-drafted, for a human to correct: it describes what the generator
    says it produced, which is the best available text proxy for a clip nobody
    has watched yet.
    """
    text = " ".join(expanded_of(rec).split())
    text = re.sub(r"^integrated_multimodal_description:\s*", "", text)
    text = re.sub(r"^\[Shot \d+\]\s*", "", text)
    cut = text.find(". ")
    return (text[: cut + 1] if 0 < cut < limit else text[:limit]).strip()
