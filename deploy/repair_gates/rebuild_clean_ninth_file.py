"""Reconstruct the clean ninth runtime file: production baseline + the authorised quote-health repair.

Byte-level splice, deliberately not a text edit:

* the production baseline supplies every byte of the result;
* the inserted block is taken verbatim (same bytes, same indentation, same comment text) from the
  already-validated dirty checkout, so the repair text is exactly the one the RED/GREEN matrix proved;
* the unrelated `generic_fallback` prompt branch and every other checkout-only difference are excluded
  by construction, because nothing else from the dirty file is read.

Guards: the anchor must be unique, the block must be absent from the baseline, and the block's shape and
anchor neighbourhood are asserted before anything is written.
"""

import hashlib
import json
import pathlib
import sys

PROD = pathlib.Path(sys.argv[1])
DIRTY = pathlib.Path(sys.argv[2])
OUT = pathlib.Path(sys.argv[3])

RETURN_ANCHOR = 'return {"answer": think + answer, "reference": refs, "prompt": re.sub(r"\\n", "  \\n", prompt), "created_at": time.time()}'
QUARTET_IF = "        if not refs and isinstance(kbinfos, dict) and isinstance(kbinfos.get(\"retrieval_health\"), dict):"
QUARTET_BODY = '            refs = {"retrieval_health": deepcopy(kbinfos["retrieval_health"])}'
EXCLUDED_MARKER = "generic_fallback"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def strip_cr(line: bytes) -> bytes:
    """The runtime file is CRLF; compare content, splice original bytes."""
    return line[:-1] if line.endswith(b"\r") else line


prod_bytes = PROD.read_bytes()
dirty_bytes = DIRTY.read_bytes()
prod = prod_bytes.split(b"\n")
dirty = dirty_bytes.split(b"\n")

anchors = [index for index, line in enumerate(prod) if strip_cr(line) == b"        " + RETURN_ANCHOR.encode()]
if len(anchors) != 1:
    sys.exit(f"ABORT: return anchor not unique in the baseline: {anchors}")
anchor = anchors[0]

hits = [index for index, line in enumerate(dirty) if strip_cr(line) == QUARTET_IF.encode()]
if len(hits) != 1:
    sys.exit(f"ABORT: repair block not unique in the checkout: {hits}")
block = dirty[hits[0] - 7 : hits[0] + 2]  # six comment lines + the guard + the assignment
if len(block) != 9:
    sys.exit(f"ABORT: unexpected block length {len(block)}")

if strip_cr(block[7]) != QUARTET_IF.encode() or strip_cr(block[8]) != QUARTET_BODY.encode():
    sys.exit("ABORT: the block is not the authorised quote-health repair")
if not strip_cr(block[0]).startswith(b"        #"):
    sys.exit("ABORT: the block does not start at its comment header")
for line in prod:
    if strip_cr(line) in (QUARTET_IF.encode(), QUARTET_BODY.encode()):
        sys.exit("ABORT: the baseline already carries the repair")

clean = prod[:anchor] + block + prod[anchor:]
clean_bytes = b"\n".join(clean)

if EXCLUDED_MARKER.encode() in clean_bytes:
    sys.exit("ABORT: the excluded generic_fallback branch is present in the result")
if clean_bytes == prod_bytes or clean_bytes == dirty_bytes:
    sys.exit("ABORT: the result equals the baseline or the dirty checkout")

OUT.write_bytes(clean_bytes)
print(json.dumps({
    "prod_sha256": sha256(prod_bytes),
    "prod_lines": len(prod),
    "anchor_line_1based": anchor + 1,
    "block_lines": len(block),
    "block_first_line": block[0].decode().strip()[:70],
    "block_last_line": block[-1].decode().strip(),
    "clean_lines": len(clean),
    "clean_sha256": sha256(clean_bytes),
    "clean_contains_excluded_marker": EXCLUDED_MARKER.encode() in clean_bytes,
    "clean_line_endings_consistent": clean_bytes.count(b"\r") == clean_bytes.count(b"\n"),
    "bytes_added": len(clean_bytes) - len(prod_bytes),
}, indent=2), flush=True)
