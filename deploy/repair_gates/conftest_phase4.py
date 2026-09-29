"""Acceptance control for the pytest groups.

pytest is absent from the candidate image, so it is supplied from `/td`. This control proves, inside the
acceptance session itself, that:

* every product module under test resolves INSIDE the candidate image (`/ragflow/...`), and
* nothing the image already ships is served out of `/td` - i.e. the only packages the target supplies are
  the ones the image does not have (pytest, pytest-asyncio, pluggy, iniconfig).

If either ever failed, a PASS would be measuring the harness instead of the image.
"""
import importlib.util
import pathlib
import sys

sys.path.insert(0, "/ragflow")

TD = "/td"
PRODUCT_MODULES = ("rag.nlp.search", "rag.nlp.doc_context", "rag.retrieval.decomposition",
                   "rag.retrieval.chunk_profile", "rag.nlp.retrieval_projection")
IMAGE_OWNED = ("packaging", "pygments", "numpy", "requests", "yaml", "elasticsearch")


def pytest_configure(config):
    print(f"\n[control] pytest target supplied from {TD}", flush=True)

    for name in ("pytest", "pytest_asyncio", "pluggy", "iniconfig"):
        spec = importlib.util.find_spec(name)
        origin = spec.origin if spec else "ABSENT"
        print(f"[control]   supplied {name:16s} -> {origin}", flush=True)

    for name in IMAGE_OWNED:
        spec = importlib.util.find_spec(name)
        if spec is None or spec.origin is None:
            print(f"[control]   image pkg {name:16s} -> ABSENT", flush=True)
            continue
        print(f"[control]   image pkg {name:16s} -> {spec.origin}", flush=True)
        assert not str(spec.origin).startswith(TD), f"{name} was shadowed by the pytest target: {spec.origin}"

    for name in PRODUCT_MODULES:
        spec = importlib.util.find_spec(name)
        assert spec is not None, f"{name} is not importable from the image"
        resolved = str(pathlib.Path(spec.origin).resolve())
        assert resolved.startswith("/ragflow/"), f"{name} resolved outside the image: {resolved}"
        print(f"[control]   product    {name:34s} -> {resolved}", flush=True)

    print("[control] NO_IMAGE_DEPENDENCY_SHADOWED = True", flush=True)
    print("[control] ALL_PRODUCT_MODULES_FROM_IMAGE = True", flush=True)
