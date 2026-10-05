#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
"""Convert legacy Office documents to PDF so the preview API can serve them.

Word, Excel and PowerPoint files from the 97-2003 era share the OLE2 compound
file container, which no browser-side renderer can read. This module shells out
to a headless LibreOffice (installed in the runtime image) and caches the PDF it
exports, so a given document is converted once no matter how often it is
previewed.
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile

# Word 97-2003, Excel 97-2003 and PowerPoint 97-2003 all begin with the OLE2
# compound file signature.
LEGACY_OFFICE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# LibreOffice startup plus filter time. A preview request must not pin a worker
# thread on a document that will never finish.
CONVERT_TIMEOUT_SECONDS = 120

# Checked after PATH so a container without a `soffice` symlink still works.
_SOFFICE_FALLBACK_PATHS = (
    "/usr/bin/soffice",
    "/usr/lib/libreoffice/program/soffice",
    "/opt/libreoffice/program/soffice",
)

# LibreOffice picks the import filter from the file extension, so an untrusted or
# missing one must not land in the temporary file name.
_DEFAULT_SUFFIX = ".doc"
_MAX_SUFFIX_LENGTH = 8


def is_legacy_office_document(data: bytes) -> bool:
    """True when the payload is an OLE2 compound file (Word/Excel/PPT 97-2003)."""
    return bool(data) and bytes(data[:8]) == LEGACY_OFFICE_MAGIC


def soffice_binary() -> str | None:
    """Path of the headless LibreOffice binary, or None when it is not installed."""
    override = os.environ.get("SOFFICE_BIN")
    if override:
        return override if os.path.exists(override) else None

    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found

    for path in _SOFFICE_FALLBACK_PATHS:
        if os.path.exists(path):
            return path

    return None


def conversion_available() -> bool:
    """Whether the deployment can convert a legacy Office document."""
    return soffice_binary() is not None


def _cache_directory() -> str:
    # ~/.ragflow is the user-level state directory the container image creates.
    path = os.path.join(os.path.expanduser("~"), ".ragflow", "office_preview")
    os.makedirs(path, exist_ok=True)
    return path


def _cache_path(cache_key: str, digest: str) -> str:
    safe_key = "".join(ch for ch in cache_key if ch.isalnum() or ch in "-_") or "document"
    return os.path.join(_cache_directory(), f"{safe_key}-{digest[:16]}.pdf")


def _suffix_for(filename: str | None) -> str:
    suffix = os.path.splitext(filename or "")[1].lower()
    if not suffix.startswith(".") or len(suffix) > _MAX_SUFFIX_LENGTH or not suffix[1:].isalnum():
        return _DEFAULT_SUFFIX
    return suffix


def _read_cached(path: str) -> bytes | None:
    try:
        if os.path.exists(path):
            with open(path, "rb") as f:
                return f.read()
    except OSError as e:
        logging.warning("Failed to read the cached Office preview %s: %s", path, e)

    return None


def _write_cache(path: str, pdf: bytes) -> None:
    try:
        # The cache directory can be removed while the server runs, so the writer
        # does not rely on the reader having created it.
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
        with os.fdopen(fd, "wb") as f:
            f.write(pdf)
        # Rename, so a concurrent conversion of the same document can never leave
        # a half-written cache entry behind.
        os.replace(tmp_path, path)
    except OSError as e:
        logging.warning("Failed to cache the converted Office preview: %s", e)


def _run_soffice(binary: str, source: str, outdir: str, profile: str) -> bool:
    cmd = [
        binary,
        "--headless",
        "--invisible",
        "--norestore",
        "--nolockcheck",
        "--nodefault",
        # A per-run profile: a second conversion fails while another soffice
        # instance holds the default one.
        f"-env:UserInstallation=file://{profile}",
        "--convert-to",
        "pdf",
        "--outdir",
        outdir,
        source,
    ]

    try:
        completed = subprocess.run(cmd, capture_output=True, timeout=CONVERT_TIMEOUT_SECONDS, check=False)
    except subprocess.TimeoutExpired:
        logging.warning("LibreOffice conversion timed out after %ss", CONVERT_TIMEOUT_SECONDS)
        return False
    except (OSError, subprocess.SubprocessError) as e:
        logging.warning("LibreOffice conversion could not run: %s", e)
        return False

    if completed.returncode != 0:
        logging.warning(
            "LibreOffice conversion failed (rc=%s): %s",
            completed.returncode,
            (completed.stderr or b"")[:500],
        )
        return False

    return True


def convert_legacy_office_to_pdf(data: bytes, cache_key: str, filename: str | None = None) -> bytes | None:
    """Export an OLE2 Office payload to PDF, reusing the on-disk cache.

    Returns None when LibreOffice is missing or the conversion fails, leaving the
    caller to serve the original bytes. ``cache_key`` identifies the document
    (its id) and ``filename`` supplies the extension LibreOffice reads the
    document type from.
    """
    binary = soffice_binary()
    if binary is None:
        logging.warning("LibreOffice is not installed: the legacy Office preview falls back to the original file")
        return None

    digest = hashlib.sha256(data).hexdigest()
    cached_path = _cache_path(cache_key, digest)

    cached = _read_cached(cached_path)
    if cached is not None:
        return cached

    with tempfile.TemporaryDirectory(prefix="ragflow-office-preview-") as workdir:
        source = os.path.join(workdir, f"source{_suffix_for(filename)}")
        with open(source, "wb") as f:
            f.write(data)

        outdir = os.path.join(workdir, "out")
        profile = os.path.join(workdir, "profile")
        os.makedirs(outdir, exist_ok=True)

        if not _run_soffice(binary, source, outdir, profile):
            return None

        produced = os.path.join(outdir, f"{os.path.splitext(os.path.basename(source))[0]}.pdf")
        # LibreOffice names the result after the input file, whatever the input
        # extension was.
        if not os.path.exists(produced):
            logging.warning("LibreOffice reported success but wrote no PDF for %s", filename)
            return None

        try:
            with open(produced, "rb") as f:
                pdf = f.read()
        except OSError as e:
            logging.warning("Failed to read the converted PDF: %s", e)
            return None

    _write_cache(cached_path, pdf)
    return pdf
