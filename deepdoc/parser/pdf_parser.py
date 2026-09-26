#
#  Copyright 2025 The InfiniFlow Authors. All Rights Reserved.
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

from __future__ import annotations

import asyncio
import logging
import math
import os
import re
import sys
import threading
import unicodedata
from collections import Counter, defaultdict
from copy import deepcopy
from io import BytesIO
from timeit import default_timer as timer
from typing import Any

import numpy as np
import pdfplumber
import xgboost as xgb
from huggingface_hub import snapshot_download
from PIL import Image
from pypdf import PdfReader as pdf2_read
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from common.constants import MAXIMUM_PAGE_NUMBER
from common.file_utils import get_project_base_directory
from deepdoc.vision import OCR, AscendLayoutRecognizer, LayoutRecognizer, Recognizer, TableStructureRecognizer
from rag.nlp import rag_tokenizer
from rag.prompts.generator import vision_llm_describe_prompt
from deepdoc.parser.utils import extract_pdf_outlines
from deepdoc.parser.domain_prompts import (
    inject_domain_instruction,
    resolve_domain_with_confidence,
)
from common import settings
from common.misc_utils import thread_pool_exec

LOCK_KEY_pdfplumber = "global_shared_lock_pdfplumber"
if LOCK_KEY_pdfplumber not in sys.modules:
    sys.modules[LOCK_KEY_pdfplumber] = threading.Lock()

# ``MAXIMUM_PAGE_NUMBER`` stays imported (and therefore re-exported) here: sibling
# parsers import it from this module rather than from ``common.constants``.

# Every coordinate in this module is a PDF user-space point. ``zoomin`` converts
# points to pixels, so a pixel measurement is divided by it and a point
# measurement multiplied by it.
DEFAULT_ZOOMIN = 3
#: PDF user-space units per inch — the resolution ``zoomin`` scales.
PDF_RENDER_DPI = 72
#: A page that yielded no box at all is re-rendered at ``zoomin * ZOOMIN_RETRY_FACTOR``
#: and retried, but never beyond ``MAX_ZOOMIN_RETRY``: past that scale the extra
#: render costs more than the recovery is worth.
ZOOMIN_RETRY_FACTOR = 3
MAX_ZOOMIN_RETRY = 9
#: Background of a stitched figure/table image (matches the page colour).
IMAGE_CANVAS_BACKGROUND = (245, 245, 245)
#: Whitespace kept around a cropped table before it is handed to the TSR model.
TABLE_CROP_MARGIN = 10

# --- Garbled-text detection (what turns the OCR fallback on) ----------------
#: Share of unmappable characters at which a text box is discarded and re-OCR'd.
GARBLED_CHAR_THRESHOLD = 0.5
#: Stricter share for the page-level sample: re-OCRing costs a whole page, so a
#: suspicion is enough there while a single box needs to be clearly broken.
GARBLED_PAGE_THRESHOLD = 0.3
#: Share of a box's characters that must come from subset fonts before the
#: font-encoding heuristic is allowed to have an opinion.
GARBLED_FONT_SUBSET_RATIO = 0.3
#: CJK below this share *and* punctuation/symbols above
#: :data:`GARBLED_FONT_PUNCT_RATIO` means a broken ToUnicode map (GB.18067-2000
#: extracts as ASCII punctuation), not a page that is genuinely punctuation.
GARBLED_FONT_CJK_RATIO = 0.05
GARBLED_FONT_PUNCT_RATIO = 0.4
#: Character counts below which the font-encoding heuristic has no opinion.
GARBLED_FONT_MIN_CHARS = 20
GARBLED_BOX_MIN_CHARS = 5
#: A box character this much shorter or taller than the OCR line it would join is
#: an annotation (superscript, footnote marker), not part of the line.
GARBLED_BOX_HEIGHT_RATIO = 0.7
#: Characters sampled from a page when testing for page-level garbage.
GARBLED_PAGE_SAMPLE_CHARS = 200
#: Share of a box's characters the OCR alphabet must be able to spell before
#: re-OCRing it can produce anything but garbage.
OCR_ALPHABET_MIN_COVERAGE = 0.8
#: Gap, as a fraction of the mean glyph width, that becomes a word space when a
#: PDF carries no space glyphs at all.
WORD_GAP_RATIO = 0.25

# --- Table orientation & structure recognition ------------------------------
#: Confidence a rotation must gain over the unrotated crop before it is applied,
#: and the unrotated score below which that gain is not trusted: an already-good
#: crop has little to gain, and OCR noise can invent one.
TABLE_ORIENTATION_MIN_GAIN = 0.2
TABLE_ORIENTATION_BASELINE_CAP = 0.8
#: Bonus for a rotation that recognises more regions, saturating at
#: :data:`TABLE_ORIENTATION_REGION_CAP` regions.
TABLE_ORIENTATION_REGION_BONUS = 0.1
TABLE_ORIENTATION_REGION_CAP = 50
#: Kept for callers that tune the probe's sampling; the probe scores the whole
#: crop, so it currently has no effect on the result.
TABLE_ORIENTATION_SAMPLE_RATIO = 0.3
#: bbox overlap above which a recognised table component is attached to a box.
TSR_OVERLAP_THRESHOLD = 0.3
#: Component cleanup: rows further apart than this many line heights are split,
#: and the ption floors keep a row/column from being absorbed into a fragment.
TSR_CLEANUP_FAR = 5
TSR_ROW_CLEANUP_PTION = 0.6
TSR_COLUMN_CLEANUP_PTION = 0.5
TSR_SORT_FZY = 10
#: OCR confidence below which a box re-read from a rotated table is dropped.
ROTATED_TABLE_MIN_CONFIDENCE = 0.5
#: Tolerance (points) when matching a table box back to its layout region.
ROTATED_TABLE_BOX_PADDING = 5

# --- Text flow: column assignment and merging ------------------------------
#: x0s within this fraction of the left margin are the same indent, so a hanging
#: indent cannot be mistaken for a second column.
COLUMN_INDENT_TOL_RATIO = 0.12
#: Upper bound on the column counts KMeans may try on one page.
COLUMN_MAX_CLUSTERS = 4
#: A vertical gap wider than this many line heights separates paragraphs.
VERTICAL_MERGE_GAP_RATIO = 1.5
#: Horizontal overlap, as a share of the narrower box, below which two boxes sit
#: in different columns and are never merged vertically.
VERTICAL_MERGE_OVERLAP_RATIO = 0.3
#: A jump across a page break wider than this many mean widths starts a new column.
VERTICAL_MERGE_PAGEBREAK_WIDTH_RATIO = 4
#: Fraction of a mean line height within which two boxes count as the same line
#: (OCR line grouping and the horizontal text merge both use "a third of a line").
LINE_MERGE_TOLERANCE_DIVISOR = 3
#: Line height assumed when a page has no measurable characters at all.
DEFAULT_LINE_HEIGHT = 10
#: Guard for the ratios in the concatenation features, where a zero denominator
#: is a legal (if degenerate) measurement.
EPSILON = 0.000001
#: Rows further apart than this many line heights are separate tables, not one
#: table split across a page break.
TABLE_STITCH_MAX_Y_DIS_RATIO = 23
#: Boxes scanned forward for a table-of-contents entry's page-number run, and
#: dirty glyphs per page above which a page is treated as OCR junk.
TOC_LOOKAHEAD_BOXES = 128
TOC_DIRTY_PAGE_MARKS = 3
#: Lines scanned forward when collecting a scrap run's continuation.
SCRAP_LOOKAHEAD_LINES = 20
#: A scrap run narrower than this share of the page, and below the absolute cap,
#: is dropped as noise.
SCRAP_MIN_WIDTH_RATIO = 0.35
SCRAP_MAX_WIDTH = 200
#: A continuation line must start within a tenth of the page width of its head.
SCRAP_X_ALIGN_DIVISOR = 10
#: Gaps (in line heights) that end a scrap run, and the head height above which a
#: box is treated as a paragraph rather than a scrap line.
SCRAP_GAP_LINES = 3
SCRAP_MAX_HEAD_HEIGHT_RATIO = 1.5

# --- Cropping & samplers ----------------------------------------------------
#: Context kept above the first and below the last crop segment, in points.
CROP_CONTEXT_HEIGHT = 120
CROP_GAP = 6
#: Width floors so a degenerate position still yields a usable image.
CROP_MIN_WIDTH = 6
CROP_MIN_SEGMENT_WIDTH = 10
#: Characters/boxes sampled when deciding whether a document is English, and the
#: run length of Latin text that decides it.
IS_ENGLISH_SAMPLE_CHARS = 100
IS_ENGLISH_SAMPLE_BOXES = 30
IS_ENGLISH_MIN_RUN = 30
#: Latin-run probe used by both English detectors. The doubled braces are the
#: literal quantifier braces; the f-string only injects the run length.
IS_ENGLISH_PATTERN = rf"[ a-zA-Z0-9,/¸;:'\[\]\(\)!@#$%^&*\"?<>._-]{{{IS_ENGLISH_MIN_RUN},}}"
#: The same probe for the OCR-box fallback, where newlines are letter runs too.
IS_ENGLISH_BOX_PATTERN = rf"[ \na-zA-Z0-9,/¸;:'\[\]\(\)!@#$%^&*\"?<>._-]{{{IS_ENGLISH_MIN_RUN},}}"
#: OCR progress is reported every N pages, as a share of the 0.6 the OCR pass
#: owns in the extraction progress bar.
OCR_PROGRESS_EVERY_PAGES = 6
OCR_PROGRESS_SHARE = 0.6


#: Seed for the column-assignment KMeans. ``KMeans`` initialises from the global
#: numpy RNG when ``random_state`` is None, so two runs of the same document could
#: start from different centroids and land on different ``col_id`` labels — which
#: reorders the reading order and therefore the chunk tokens. The clustering it
#: pins is the same one it always ran (same k search, same silhouette choice).
KMEANS_RANDOM_STATE = 0


def _evenly_spaced(items: list[Any], count: int) -> list[Any]:
    """Take ``count`` items from ``items`` at an even stride — deterministically.

    The English probe only needs a representative slice of a page, and it sampled
    with ``random.choices``: the drawn slice could contain a 30+ character Latin
    run on one run and not on the next, which flips the document between the
    English path and the OCR-only path and made a before/after digest comparison
    meaningless. An even stride is a pure function of the input and is also the
    better sample: a head slice would only ever see a page's title area, and a
    replacement sample can repeat the same character.
    """
    total = len(items)
    if count <= 0:
        return []
    if count >= total:
        return list(items)
    step = total / count
    return [items[int(i * step)] for i in range(count)]


# --- Failure taxonomy -------------------------------------------------------
# Only failures this module actually handles are named; anything else is a defect
# here rather than a condition to swallow, so it is reported with a stack trace
# instead. The imports are guarded and filtered because this module is loaded
# directly by unit tests that stub pdfplumber / pypdf / xgboost: a hard import
# from a submodule of a stubbed package would break collection, and a stubbed
# attribute is a placeholder object, not an exception class — one of those inside
# an ``except`` tuple would turn a handled failure into a ``TypeError``.

try:
    from pdfminer.pdfdocument import PDFEncryptionError, PDFPasswordIncorrect
    from pdfminer.pdfparser import PDFSyntaxError
    from pdfminer.psparser import PSException

    _PDFMINER_ERRORS: tuple[Any, ...] = (PDFSyntaxError, PDFEncryptionError, PDFPasswordIncorrect, PSException)
except ImportError:  # pragma: no cover - depends on the deployed PDF stack
    _PDFMINER_ERRORS = ()

try:
    from pypdf.errors import PdfReadError

    _PYPDF_ERRORS: tuple[Any, ...] = (PdfReadError,)
except ImportError:  # pragma: no cover - depends on the deployed PDF stack
    _PYPDF_ERRORS = ()

try:
    from xgboost.core import XGBoostError

    _XGBOOST_ERRORS: tuple[Any, ...] = (XGBoostError,)
except ImportError:  # pragma: no cover - depends on the deployed PDF stack
    _XGBOOST_ERRORS = ()


def _error_types(*candidates: Any) -> tuple[type[Exception], ...]:
    """Filter ``candidates`` down to real exception classes (see the note above)."""
    return tuple(c for c in candidates if isinstance(c, type) and issubclass(c, Exception))


#: "This file cannot be read": a missing or unreadable path, a malformed PDF, or
#: an encrypted one. Callers report these and carry on with no content; anything
#: else escaping a parse is a bug and is logged with its stack.
PDF_READ_ERRORS: tuple[type[Exception], ...] = (OSError, *_error_types(*_PDFMINER_ERRORS, *_PYPDF_ERRORS))
#: Failures of the local concatenation model (missing file, unreadable booster).
MODEL_LOAD_ERRORS: tuple[type[Exception], ...] = (OSError, *_error_types(*_XGBOOST_ERRORS))


class RAGFlowPdfParser:
    def __init__(self, **kwargs):
        """
        If you have trouble downloading HuggingFace models, -_^ this might help!!

        For Linux:
        export HF_ENDPOINT=https://hf-mirror.com

        For Windows:
        Good luck
        ^_-

        """

        self.ocr = OCR()
        self.parallel_limiter = None
        if settings.PARALLEL_DEVICES > 1:
            self.parallel_limiter = [asyncio.Semaphore(1) for _ in range(settings.PARALLEL_DEVICES)]

        layout_recognizer_type = os.getenv("LAYOUT_RECOGNIZER_TYPE", "onnx").lower()
        if layout_recognizer_type not in ["onnx", "ascend"]:
            raise RuntimeError("Unsupported layout recognizer type.")

        if hasattr(self, "model_species"):
            recognizer_domain = "layout." + self.model_species
        else:
            recognizer_domain = "layout"

        if layout_recognizer_type == "ascend":
            logging.debug("Using Ascend LayoutRecognizer")
            self.layouter = AscendLayoutRecognizer(recognizer_domain)
        else:  # onnx
            logging.debug("Using Onnx LayoutRecognizer")
            self.layouter = LayoutRecognizer(recognizer_domain)
        self.tbl_det = TableStructureRecognizer()

        self.updown_cnt_mdl = xgb.Booster()
        # xgboost model is very small; using CPU explicitly
        self.updown_cnt_mdl.set_param({"device": "cpu"})
        logging.info("updown_cnt_mdl initialized on CPU")
        try:
            model_dir = os.path.join(get_project_base_directory(), "rag/res/deepdoc")
            self.updown_cnt_mdl.load_model(os.path.join(model_dir, "updown_concat_xgb.model"))
        except MODEL_LOAD_ERRORS:
            # The bundled booster is missing or unreadable (a checkout that never
            # fetched rag/res/deepdoc, or a truncated download). Fetch it and retry;
            # a failure there is an installation defect, so it propagates with its
            # stack instead of being swallowed.
            logging.exception("updown_concat_xgb.model is not usable under %s; fetching it from the hub", get_project_base_directory())
            model_dir = snapshot_download(repo_id="InfiniFlow/text_concat_xgb_v1.0", local_dir=os.path.join(get_project_base_directory(), "rag/res/deepdoc"))
            self.updown_cnt_mdl.load_model(os.path.join(model_dir, "updown_concat_xgb.model"))

        self.page_from = 0
        self.column_num = 1

    def __char_width(self, c: dict[str, Any]) -> float:
        return (c["x1"] - c["x0"]) // max(len(c["text"]), 1)

    def __height(self, c: dict[str, Any]) -> float:
        return c["bottom"] - c["top"]

    def _x_dis(self, a: dict[str, Any], b: dict[str, Any]) -> float:
        return min(abs(a["x1"] - b["x0"]), abs(a["x0"] - b["x1"]), abs(a["x0"] + a["x1"] - b["x0"] - b["x1"]) / 2)

    def _y_dis(self, a: dict[str, Any], b: dict[str, Any]) -> float:
        return (b["top"] + b["bottom"] - a["top"] - a["bottom"]) / 2

    def _match_proj(self, b: dict[str, Any]) -> bool:
        proj_patt = [
            r"第[零一二三四五六七八九十百]+章",
            r"第[零一二三四五六七八九十百]+[条节]",
            r"[零一二三四五六七八九十百]+[、是  ]",
            r"[\(（][零一二三四五六七八九十百]+[）\)]",
            r"[\(（][0-9]+[）\)]",
            r"[0-9]+(、|\.[  ]|）|\.[^0-9./a-zA-Z_%><-]{4,})",
            r"[0-9]+\.[0-9.]+(、|\.[  ])",
            r"[⚫•➢①② ]",
        ]
        return any([re.match(p, b["text"]) for p in proj_patt])

    def _updown_concat_features(self, up: dict[str, Any], down: dict[str, Any]) -> list[Any]:
        w = max(self.__char_width(up), self.__char_width(down))
        h = max(self.__height(up), self.__height(down))
        y_dis = self._y_dis(up, down)
        # Characters of context taken from each side of the boundary.
        LEN = 6
        tks_down = rag_tokenizer.tokenize(down["text"][:LEN]).split()
        tks_up = rag_tokenizer.tokenize(up["text"][-LEN:]).split()
        tks_all = up["text"][-LEN:].strip() + (" " if re.match(r"[a-zA-Z0-9]+", up["text"][-1] + down["text"][0]) else "") + down["text"][:LEN].strip()
        tks_all = rag_tokenizer.tokenize(tks_all).split()
        fea = [
            up.get("R", -1) == down.get("R", -1),
            y_dis / h,
            down["page_number"] - up["page_number"],
            up["layout_type"] == down["layout_type"],
            up["layout_type"] == "text",
            down["layout_type"] == "text",
            up["layout_type"] == "table",
            down["layout_type"] == "table",
            True if re.search(r"([。？！；!?;+)）]|[a-z]\.)$", up["text"]) else False,
            True if re.search(r"[，：‘“、0-9（+-]$", up["text"]) else False,
            True if re.search(r"(^.?[/,?;:\]，。；：’”？！》】）-])", down["text"]) else False,
            True if re.match(r"[\(（][^\(\)（）]+[）\)]$", up["text"]) else False,
            True if re.search(r"[，,][^。.]+$", up["text"]) else False,
            True if re.search(r"[，,][^。.]+$", up["text"]) else False,
            True if re.search(r"[\(（][^\)）]+$", up["text"]) and re.search(r"[\)）]", down["text"]) else False,
            self._match_proj(down),
            True if re.match(r"[A-Z]", down["text"]) else False,
            True if re.match(r"[A-Z]", up["text"][-1]) else False,
            True if re.match(r"[a-z0-9]", up["text"][-1]) else False,
            True if re.match(r"[0-9.%,-]+$", down["text"]) else False,
            up["text"].strip()[-2:] == down["text"].strip()[-2:] if len(up["text"].strip()) > 1 and len(down["text"].strip()) > 1 else False,
            up["x0"] > down["x1"],
            abs(self.__height(up) - self.__height(down)) / min(self.__height(up), self.__height(down)),
            self._x_dis(up, down) / max(w, EPSILON),
            (len(up["text"]) - len(down["text"])) / max(len(up["text"]), len(down["text"])),
            len(tks_all) - len(tks_up) - len(tks_down),
            len(tks_down) - len(tks_up),
            tks_down[-1] == tks_up[-1] if tks_down and tks_up else False,
            max(down["in_row"], up["in_row"]),
            abs(down["in_row"] - up["in_row"]),
            len(tks_down) == 1 and rag_tokenizer.tag(tks_down[0]).find("n") >= 0,
            len(tks_up) == 1 and rag_tokenizer.tag(tks_up[0]).find("n") >= 0,
        ]
        return fea

    @staticmethod
    def sort_X_by_page(arr: list[dict[str, Any]], threshold: float) -> list[dict[str, Any]]:
        arr = sorted(arr, key=lambda r: (r["page_number"], r["x0"], r["top"]))
        for i in range(len(arr) - 1):
            for j in range(i, -1, -1):
                if abs(arr[j + 1]["x0"] - arr[j]["x0"]) < threshold and arr[j + 1]["top"] < arr[j]["top"] and arr[j + 1]["page_number"] == arr[j]["page_number"]:
                    tmp = arr[j]
                    arr[j] = arr[j + 1]
                    arr[j + 1] = tmp
        return arr

    def _has_color(self, o: dict[str, Any]) -> bool:
        if o.get("ncs", "") == "DeviceGray":
            if o["stroking_color"] and o["stroking_color"][0] == 1 and o["non_stroking_color"] and o["non_stroking_color"][0] == 1:
                if re.match(r"[a-zT_\[\]\(\)-]+", o.get("text", "")):
                    return False
        return True

    _CID_PATTERN = re.compile(r"\(cid\s*:\s*\d+\s*\)")
    _OCR_ALPHABET = None

    @classmethod
    def _ocr_can_represent(cls, text: str, min_coverage: float = OCR_ALPHABET_MIN_COVERAGE) -> bool:
        if not text:
            return True
        if cls._OCR_ALPHABET is None:
            res = os.path.join(get_project_base_directory(), "rag/res/deepdoc/ocr.res")
            try:
                with open(res, encoding="utf-8") as f:
                    cls._OCR_ALPHABET = set(f.read())
            except (OSError, UnicodeDecodeError) as e:
                logging.warning("Could not load OCR alphabet from %s: %s; treating all text as representable.", res, e)
                cls._OCR_ALPHABET = set()
        if not cls._OCR_ALPHABET:
            return True
        letters = [c for c in text if c.strip()]
        if not letters:
            return True
        covered = sum(1 for c in letters if c in cls._OCR_ALPHABET)
        return covered / len(letters) >= min_coverage

    _CJK_PATTERN = re.compile(r"[ᄀ-ᇿ぀-ヿ㄰-㆏㐀-䶿一-鿿가-힯豈-﫿]|[\U00020000-\U0002fa1f]")

    @classmethod
    def _insert_word_spaces(cls, chars: list[dict[str, Any]], gap_ratio: float = WORD_GAP_RATIO) -> None:
        widths = [c["width"] for c in chars if c["text"] and c["text"].strip()]
        mean_w = sum(widths) / len(widths) if widths else 0
        if mean_w <= 0:
            return
        for cur, nxt in zip(chars, chars[1:]):
            if (
                cur["text"]
                and nxt["text"]
                and cur["text"].strip()
                and nxt["text"].strip()
                and not cls._CJK_PATTERN.search(cur["text"])
                and not cls._CJK_PATTERN.search(nxt["text"])
                and nxt["x0"] - cur["x1"] > mean_w * gap_ratio
            ):
                cur["text"] += " "

    @staticmethod
    def _is_garbled_char(ch: str) -> bool:
        if not ch:
            return False
        cp = ord(ch)
        if 0xE000 <= cp <= 0xF8FF or 0xF0000 <= cp <= 0xFFFFF or 0x100000 <= cp <= 0x10FFFF or cp == 0xFFFD:
            return True
        if cp < 0x20 and ch not in ("\t", "\n", "\r"):
            return True
        if 0x80 <= cp <= 0x9F:
            return True
        cat = unicodedata.category(ch)
        if cat in ("Cn", "Cs"):
            return True
        return False

    @staticmethod
    def _is_garbled_text(text: str | None, threshold: float = GARBLED_CHAR_THRESHOLD) -> bool:
        if not text or not text.strip():
            return False
        if RAGFlowPdfParser._CID_PATTERN.search(text):
            return True
        garbled_count = 0
        total = 0
        for ch in text:
            if ch.isspace():
                continue
            total += 1
            if RAGFlowPdfParser._is_garbled_char(ch):
                garbled_count += 1
        if total == 0:
            return False
        return garbled_count / total >= threshold

    @staticmethod
    def _has_subset_font_prefix(fontname: str | None) -> bool:
        if not fontname:
            return False
        return bool(re.match(r"^[A-Z0-9]{2,6}\+", fontname))

    @staticmethod
    def _is_garbled_by_font_encoding(page_chars: list[dict[str, Any]] | None, min_chars: int = GARBLED_FONT_MIN_CHARS) -> bool:
        if not page_chars or len(page_chars) < min_chars:
            return False

        subset_font_count = 0
        total_non_space = 0
        ascii_punct_sym = 0
        cjk_like = 0

        for c in page_chars:
            text = c.get("text", "")
            fontname = c.get("fontname", "")
            if not text or text.isspace():
                continue
            total_non_space += 1

            if RAGFlowPdfParser._has_subset_font_prefix(fontname):
                subset_font_count += 1

            cp = ord(text[0])
            if 0x2E80 <= cp <= 0x9FFF or 0xF900 <= cp <= 0xFAFF or 0x20000 <= cp <= 0x2FA1F or 0xAC00 <= cp <= 0xD7AF or 0x3040 <= cp <= 0x30FF:
                cjk_like += 1
            elif 0x21 <= cp <= 0x2F or 0x3A <= cp <= 0x40 or 0x5B <= cp <= 0x60 or 0x7B <= cp <= 0x7E:
                ascii_punct_sym += 1

        if total_non_space < min_chars:
            return False

        subset_ratio = subset_font_count / total_non_space
        if subset_ratio < GARBLED_FONT_SUBSET_RATIO:
            return False

        cjk_ratio = cjk_like / total_non_space
        punct_ratio = ascii_punct_sym / total_non_space
        if cjk_ratio < GARBLED_FONT_CJK_RATIO and punct_ratio > GARBLED_FONT_PUNCT_RATIO:
            return True

        return False

    def _evaluate_table_orientation(self, table_img: Any, sample_ratio: float = TABLE_ORIENTATION_SAMPLE_RATIO) -> tuple[int, Any, dict[int, dict[str, float]]]:
        """Pick the rotation whose crop the OCR is most confident about.

        ``sample_ratio`` is part of the caller's surface and is passed through
        unchanged, but the probe scores the WHOLE crop — sampling it would change
        which rotation wins, and the rotation feeds back into table coordinates.
        """
        rotations = [
            (0, "original"),
            (90, "rotate_90"),
            (180, "rotate_180"),
            (270, "rotate_270"),
        ]

        results: dict[int, dict[str, float]] = {}
        best_score = -1
        best_angle = 0
        best_img = table_img
        score_0 = None

        for angle, name in rotations:
            rotated_img = table_img if angle == 0 else table_img.rotate(-angle, expand=True)
            img_array = np.array(rotated_img)

            try:
                ocr_results = self.ocr(img_array)
                if ocr_results:
                    scores = [conf for _, (_, conf) in ocr_results]
                    avg_score = sum(scores) / len(scores) if scores else 0
                    total_regions = len(scores)
                    combined_score = avg_score * (1 + TABLE_ORIENTATION_REGION_BONUS * min(total_regions, TABLE_ORIENTATION_REGION_CAP) / TABLE_ORIENTATION_REGION_CAP)
                else:
                    avg_score = 0
                    total_regions = 0
                    combined_score = 0
            except Exception:
                # The OCR engine failed on one of four probes. Scoring that probe
                # zero is the point of the fallback, but the reason it failed is
                # still needed to tell a broken model from an unusable crop.
                logging.exception("OCR failed while scoring table rotation %s", angle)
                avg_score = 0
                total_regions = 0
                combined_score = 0

            results[angle] = {"avg_confidence": avg_score, "total_regions": total_regions, "combined_score": combined_score}
            if angle == 0:
                score_0 = combined_score

            logging.debug(f"Table orientation {angle}°: avg_conf={avg_score:.4f}, regions={total_regions}, combined={combined_score:.4f}")

            if combined_score > best_score:
                best_score = combined_score
                best_angle = angle
                best_img = rotated_img

        if best_angle != 0 and score_0 is not None:
            if not (best_score - score_0 > TABLE_ORIENTATION_MIN_GAIN and score_0 < TABLE_ORIENTATION_BASELINE_CAP):
                best_angle = 0
                best_img = table_img
                best_score = score_0

        results[best_angle] = results.get(best_angle, {"avg_confidence": 0, "total_regions": 0, "combined_score": 0})
        logging.info(f"Best table orientation: {best_angle}° (score={best_score:.4f})")
        return best_angle, best_img, results

    @staticmethod
    def _map_clockwise_rotated_point_to_original(x: float, y: float, angle: int, width: float, height: float) -> tuple[float, float]:
        if angle == 0:
            return x, y
        if angle == 90:
            return y, height - x
        if angle == 180:
            return width - x, height - y
        if angle == 270:
            return width - y, x
        return x, y

    def _table_transformer_job(self, ZM: int, auto_rotate: bool | None = None) -> None:
        if auto_rotate is None:
            auto_rotate = os.getenv("TABLE_AUTO_ROTATE", "true").lower() in ("true", "1", "yes")

        logging.debug("Table processing...")
        imgs, pos = [], []
        tbcnt = [0]
        MARGIN = TABLE_CROP_MARGIN
        self.tb_cpns = []
        self.table_rotations = {}
        self.rotated_table_imgs = {}

        assert len(self.page_layout) == len(self.page_images)
        table_layouts = []

        table_index = 0
        for p, tbls in enumerate(self.page_layout):
            tbls = [f for f in tbls if f["type"] == "table"]
            tbcnt.append(len(tbls))
            if not tbls:
                continue
            for page_table_index, tb in enumerate(tbls):
                left, top, right, bott = tb["x0"] - MARGIN, tb["top"] - MARGIN, tb["x1"] + MARGIN, tb["bottom"] + MARGIN
                left *= ZM
                top *= ZM
                right *= ZM
                bott *= ZM
                layoutno = f"table-{page_table_index}"
                pos.append((left, top, p, table_index, layoutno))

                table_layouts.append({"page": p, "table_index": table_index, "layoutno": layoutno, "layout": tb, "coords": (left, top, right, bott)})
                table_img = self.page_images[p].crop((left, top, right, bott))

                if auto_rotate:
                    logging.debug(f"Evaluating orientation for table {table_index} on page {p}")
                    best_angle, rotated_img, rotation_scores = self._evaluate_table_orientation(table_img)

                    self.table_rotations[table_index] = {
                        "page": p,
                        "original_pos": (left, top, right, bott),
                        "best_angle": best_angle,
                        "scores": rotation_scores,
                        "rotated_size": rotated_img.size,
                    }
                    self.rotated_table_imgs[table_index] = rotated_img
                    imgs.append(rotated_img)
                else:
                    imgs.append(table_img)
                    self.table_rotations[table_index] = {"page": p, "original_pos": (left, top, right, bott), "best_angle": 0, "scores": {}, "rotated_size": table_img.size}
                    self.rotated_table_imgs[table_index] = table_img

                table_index += 1

        assert len(self.page_images) == len(tbcnt) - 1
        if not imgs:
            return

        recos = self.tbl_det(imgs)

        if auto_rotate:
            self._ocr_rotated_tables(ZM, table_layouts, recos, tbcnt)

        def _map_tsr_component_to_page_space(component: dict[str, Any], table_pos: tuple[float, float, int, int, str]) -> None:
            crop_left, crop_top, page, table_index, _ = table_pos
            rotation_info = self.table_rotations.get(table_index, {})
            angle = rotation_info.get("best_angle", 0)
            original_pos = rotation_info.get("original_pos", (crop_left, crop_top, crop_left, crop_top))
            width = original_pos[2] - original_pos[0]
            height = original_pos[3] - original_pos[1]
            points = [
                (component["x0_rotated"], component["top_rotated"]),
                (component["x1_rotated"], component["top_rotated"]),
                (component["x0_rotated"], component["bottom_rotated"]),
                (component["x1_rotated"], component["bottom_rotated"]),
            ]
            mapped = [self._map_clockwise_rotated_point_to_original(x, y, angle, width, height) for x, y in points]
            xs = [p[0] for p in mapped]
            ys = [p[1] for p in mapped]
            component["x0"] = min(xs) / ZM + crop_left / ZM
            component["x1"] = max(xs) / ZM + crop_left / ZM
            component["top"] = min(ys) / ZM + crop_top / ZM + self.page_cum_height[page]
            component["bottom"] = max(ys) / ZM + crop_top / ZM + self.page_cum_height[page]

        tbcnt = np.cumsum(tbcnt)
        for i in range(len(tbcnt) - 1):
            pg = []
            for j, tb_items in enumerate(recos[tbcnt[i] : tbcnt[i + 1]]):
                poss = pos[tbcnt[i] : tbcnt[i + 1]]
                for it in tb_items:
                    it["x0_rotated"] = it["x0"]
                    it["x1_rotated"] = it["x1"]
                    it["top_rotated"] = it["top"]
                    it["bottom_rotated"] = it["bottom"]
                    it["pn"] = poss[j][2]
                    it["layoutno"] = poss[j][4]
                    it["table_index"] = poss[j][3]
                    _map_tsr_component_to_page_space(it, poss[j])
                    pg.append(it)
            self.tb_cpns.extend(pg)

        def gather(kwd: str, fzy: float = TSR_SORT_FZY, ption: float = TSR_ROW_CLEANUP_PTION) -> list[dict[str, Any]]:
            eles = Recognizer.sort_Y_firstly([r for r in self.tb_cpns if re.match(kwd, r["label"])], fzy)
            eles = Recognizer.layouts_cleanup(self.boxes, eles, TSR_CLEANUP_FAR, ption)
            return Recognizer.sort_Y_firstly(eles, 0)

        headers = gather(r".*header$")
        rows = gather(r".* (row|header)")
        spans = gather(r".*spanning")
        clmns = sorted([r for r in self.tb_cpns if re.match(r"table column$", r["label"])], key=lambda x: (x["pn"], x["layoutno"], x["x0"]))
        clmns = Recognizer.layouts_cleanup(self.boxes, clmns, TSR_CLEANUP_FAR, TSR_COLUMN_CLEANUP_PTION)

        for b in self.boxes:
            if b.get("layout_type", "") != "table":
                continue
            ii = Recognizer.find_overlapped_with_threshold(b, rows, thr=TSR_OVERLAP_THRESHOLD)
            if ii is not None:
                b["R"] = ii
                b["R_top"] = rows[ii]["top"]
                b["R_bott"] = rows[ii]["bottom"]

            ii = Recognizer.find_overlapped_with_threshold(b, headers, thr=TSR_OVERLAP_THRESHOLD)
            if ii is not None:
                b["H_top"] = headers[ii]["top"]
                b["H_bott"] = headers[ii]["bottom"]
                b["H_left"] = headers[ii]["x0"]
                b["H_right"] = headers[ii]["x1"]
                b["H"] = ii

            ii = Recognizer.find_horizontally_tightest_fit(b, clmns)
            if ii is not None:
                b["C"] = ii
                b["C_left"] = clmns[ii]["x0"]
                b["C_right"] = clmns[ii]["x1"]

            ii = Recognizer.find_overlapped_with_threshold(b, spans, thr=TSR_OVERLAP_THRESHOLD)
            if ii is not None:
                b["H_top"] = spans[ii]["top"]
                b["H_bott"] = spans[ii]["bottom"]
                b["H_left"] = spans[ii]["x0"]
                b["H_right"] = spans[ii]["x1"]
                b["SP"] = ii

    def _ocr_rotated_tables(self, ZM: int, table_layouts: list[dict[str, Any]], tsr_results: list[Any], tbcnt: list[int]) -> None:
        tbcnt = np.cumsum(tbcnt)

        def _table_region(layout: dict[str, Any], page_index: int) -> tuple[float, float, float, float, float, float]:
            table_x0 = layout["x0"]
            table_top = layout["top"]
            table_x1 = layout["x1"]
            table_bottom = layout["bottom"]
            table_top_cum = table_top + self.page_cum_height[page_index]
            table_bottom_cum = table_bottom + self.page_cum_height[page_index]
            return table_x0, table_top, table_x1, table_bottom, table_top_cum, table_bottom_cum

        def _collect_table_boxes(page_index: int, table_x0: float, table_x1: float, table_top_cum: float, table_bottom_cum: float) -> tuple[list[dict[str, Any]], int]:
            indices = [
                i
                for i, b in enumerate(self.boxes)
                if (
                    b.get("page_number") == page_index + self.page_from
                    and b.get("layout_type") == "table"
                    and b["x0"] >= table_x0 - ROTATED_TABLE_BOX_PADDING
                    and b["x1"] <= table_x1 + ROTATED_TABLE_BOX_PADDING
                    and b["top"] >= table_top_cum - ROTATED_TABLE_BOX_PADDING
                    and b["bottom"] <= table_bottom_cum + ROTATED_TABLE_BOX_PADDING
                )
            ]
            original_boxes = [self.boxes[i] for i in indices]
            insert_at = indices[0] if indices else len(self.boxes)
            for i in reversed(indices):
                self.boxes.pop(i)
            return original_boxes, insert_at

        def _restore_boxes(original_boxes: list[dict[str, Any]], insert_at: int) -> int:
            for b in original_boxes:
                self.boxes.insert(insert_at, b)
                insert_at += 1
            return insert_at

        def _insert_ocr_boxes(
            ocr_results: list[Any],
            page_index: int,
            crop_left: float,
            crop_top: float,
            insert_at: int,
            table_index: int,
            layoutno: str,
            best_angle: int,
            table_w_px: float,
            table_h_px: float,
        ) -> int:
            added = 0
            for bbox, (text, conf) in ocr_results:
                if conf < ROTATED_TABLE_MIN_CONFIDENCE:
                    continue
                mapped = [self._map_clockwise_rotated_point_to_original(p[0], p[1], best_angle, table_w_px, table_h_px) for p in bbox]
                x_coords = [p[0] for p in mapped]
                y_coords = [p[1] for p in mapped]
                box_x0 = min(x_coords) / ZM
                box_x1 = max(x_coords) / ZM
                box_top = min(y_coords) / ZM
                box_bottom = max(y_coords) / ZM
                new_box = {
                    "text": text,
                    "x0": box_x0 + crop_left / ZM,
                    "x1": box_x1 + crop_left / ZM,
                    "top": box_top + crop_top / ZM + self.page_cum_height[page_index],
                    "bottom": box_bottom + crop_top / ZM + self.page_cum_height[page_index],
                    "page_number": page_index + self.page_from,
                    "layout_type": "table",
                    "layoutno": layoutno,
                    "_rotated": True,
                    "_rotation_angle": best_angle,
                    "_table_index": table_index,
                    "_rotated_x0": box_x0,
                    "_rotated_x1": box_x1,
                    "_rotated_top": box_top,
                    "_rotated_bottom": box_bottom,
                }
                self.boxes.insert(insert_at, new_box)
                insert_at += 1
                added += 1
            return added

        for tbl_info in table_layouts:
            table_index = tbl_info["table_index"]
            page = tbl_info["page"]
            layout = tbl_info["layout"]
            layoutno = tbl_info["layoutno"]
            left, top, right, bott = tbl_info["coords"]

            rotation_info = self.table_rotations.get(table_index, {})
            best_angle = rotation_info.get("best_angle", 0)

            rotated_img = self.rotated_table_imgs.get(table_index)
            if rotated_img is None or best_angle == 0:
                continue

            table_x0, table_top, table_x1, table_bottom, table_top_cum, table_bottom_cum = _table_region(layout, page)
            original_boxes, insert_at = _collect_table_boxes(page, table_x0, table_x1, table_top_cum, table_bottom_cum)

            logging.info(f"Re-OCR table {table_index} on page {page} with rotation {best_angle}°")

            img_array = np.array(rotated_img)
            ocr_results = self.ocr(img_array)

            if not ocr_results:
                logging.warning(f"No OCR results for rotated table {table_index}, restoring originals")
                _restore_boxes(original_boxes, insert_at)
                continue

            table_w_px = right - left
            table_h_px = bott - top
            added = _insert_ocr_boxes(
                ocr_results,
                page,
                left,
                top,
                insert_at,
                table_index,
                layoutno,
                best_angle,
                table_w_px,
                table_h_px,
            )

            logging.info(f"Added {added} OCR results from rotated table {table_index}")

    def __ocr(self, pagenum: int, img: Any, chars: list[dict[str, Any]], ZM: int = DEFAULT_ZOOMIN, device_id: int | None = None) -> None:
        bxs = self.ocr.detect(np.array(img), device_id)
        if not bxs:
            self.boxes.append([])
            return
        bxs = [(line[0], line[1][0]) for line in bxs]
        bxs = Recognizer.sort_Y_firstly(
            [
                {"x0": b[0][0] / ZM, "x1": b[1][0] / ZM, "top": b[0][1] / ZM, "text": "", "txt": t, "bottom": b[-1][1] / ZM, "chars": [], "page_number": pagenum}
                for b, t in bxs
                if b[0][0] <= b[1][0] and b[0][1] <= b[-1][1]
            ],
            self.mean_height[pagenum - 1] / LINE_MERGE_TOLERANCE_DIVISOR,
        )

        for c in chars:
            ii = Recognizer.find_overlapped(c, bxs)
            if ii is None:
                self.lefted_chars.append(c)
                continue
            ch = c["bottom"] - c["top"]
            bh = bxs[ii]["bottom"] - bxs[ii]["top"]
            if abs(ch - bh) / max(ch, bh) >= GARBLED_BOX_HEIGHT_RATIO and c["text"] != " ":
                self.lefted_chars.append(c)
                continue
            bxs[ii]["chars"].append(c)

        for b in bxs:
            if not b["chars"]:
                del b["chars"]
                continue
            box_chars = b["chars"]
            m_ht = np.mean([c["height"] for c in box_chars])
            garbled_count = 0
            total_count = 0
            for c in Recognizer.sort_Y_firstly(box_chars, m_ht):
                if c["text"] == " " and b["text"]:
                    if re.match(r"[0-9a-zA-Zа-яА-Я,.?;:!%%]", b["text"][-1]):
                        b["text"] += " "
                else:
                    b["text"] += c["text"]
                    for ch in c["text"]:
                        if not ch.isspace():
                            total_count += 1
                            if self._is_garbled_char(ch):
                                garbled_count += 1
            del b["chars"]

            if total_count > 0 and garbled_count / total_count >= GARBLED_CHAR_THRESHOLD:
                logging.info(
                    "Page %d: detected garbled pdfplumber text (garbled=%d/%d), falling back to OCR for box at (%.1f, %.1f)",
                    pagenum,
                    garbled_count,
                    total_count,
                    b["x0"],
                    b["top"],
                )
                b["text"] = ""
                continue

            if total_count > 0 and not self._ocr_can_represent(b["text"]):
                continue

            if total_count > 0 and self._is_garbled_by_font_encoding(box_chars, min_chars=GARBLED_BOX_MIN_CHARS):
                logging.info(
                    "Page %d: detected font-encoding garbled text (%d chars), falling back to OCR for box at (%.1f, %.1f)",
                    pagenum,
                    total_count,
                    b["x0"],
                    b["top"],
                )
                b["text"] = ""

        boxes_to_reg = []
        crop_boxes = []
        for b in bxs:
            if not b["text"]:
                left, right, top, bott = b["x0"] * ZM, b["x1"] * ZM, b["top"] * ZM, b["bottom"] * ZM
                crop_boxes.append(np.array([[left, top], [right, top], [right, bott], [left, bott]], dtype=np.float32))
                boxes_to_reg.append(b)
            del b["txt"]
        if boxes_to_reg:
            crops = self.ocr.get_rotate_crop_images(np.asarray(img), crop_boxes)
            for box, crop in zip(boxes_to_reg, crops):
                box["box_image"] = crop
        texts = self.ocr.recognize_batch([b["box_image"] for b in boxes_to_reg], device_id)
        for i in range(len(boxes_to_reg)):
            boxes_to_reg[i]["text"] = texts[i]
            del boxes_to_reg[i]["box_image"]

        bxs = [b for b in bxs if b["text"]]
        if self.mean_height[pagenum - 1] == 0:
            self.mean_height[pagenum - 1] = np.median([b["bottom"] - b["top"] for b in bxs])
        self.boxes.append(bxs)

    def _layouts_rec(self, ZM: int, drop: bool = True) -> None:
        assert len(self.page_images) == len(self.boxes)
        self.boxes, self.page_layout = self.layouter(self.page_images, self.boxes, ZM, drop=drop)
        for i in range(len(self.boxes)):
            self.boxes[i]["top"] += self.page_cum_height[self.boxes[i]["page_number"] - 1]
            self.boxes[i]["bottom"] += self.page_cum_height[self.boxes[i]["page_number"] - 1]

    def _assign_column(self, boxes: list[dict[str, Any]], zoomin: int = DEFAULT_ZOOMIN) -> list[dict[str, Any]]:
        """Tag every box with ``col_id`` — its column on its page.

        KMeans over the box left edges, tried for 1..:data:`COLUMN_MAX_CLUSTERS`
        columns, scored by silhouette; the count the majority of pages agree on
        becomes the document's column count. ``zoomin`` is accepted because the
        callers pass the render scale, but the clustering only ever sees
        coordinates that are already in PDF points.
        """
        if not boxes or all("col_id" in b for b in boxes):
            return boxes

        by_page: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for b in boxes:
            by_page[b["page_number"]].append(b)

        page_cols: dict[int, int] = {}
        for pg, bxs in by_page.items():
            if not bxs:
                page_cols[pg] = 1
                continue

            x0s_raw = np.array([b["x0"] for b in bxs], dtype=float)
            min_x0 = np.min(x0s_raw)
            max_x1 = np.max([b["x1"] for b in bxs])
            width = max_x1 - min_x0

            INDENT_TOL = width * COLUMN_INDENT_TOL_RATIO
            x0s = []
            for x in x0s_raw:
                if abs(x - min_x0) < INDENT_TOL:
                    x0s.append([min_x0])
                else:
                    x0s.append([x])
            x0s = np.array(x0s, dtype=float)

            max_try = min(COLUMN_MAX_CLUSTERS, len(bxs))
            if max_try < 2:
                max_try = 1
            best_k = 1
            best_score = -1

            for k in range(1, max_try + 1):
                km = KMeans(n_clusters=k, n_init="auto", random_state=KMEANS_RANDOM_STATE)
                labels = km.fit_predict(x0s)

                centers = np.sort(km.cluster_centers_.flatten())
                if len(centers) > 1:
                    try:
                        score = silhouette_score(x0s, labels)
                    except ValueError:
                        # Fewer distinct points than clusters: this k is not
                        # scoreable, which is not a reason to abandon the page.
                        logging.debug("[Page %s] silhouette undefined for k=%s; skipping", pg, k)
                        continue
                else:
                    score = 0
                if score > best_score:
                    best_score = score
                    best_k = k

            page_cols[pg] = best_k
            logging.info(f"[Page {pg}] best_score={best_score:.2f}, best_k={best_k}")

        global_cols = Counter(page_cols.values()).most_common(1)[0][0]
        logging.info(f"Global column_num decided by majority: {global_cols}")

        for pg, bxs in by_page.items():
            if not bxs:
                continue
            k = page_cols[pg]
            if len(bxs) < k:
                k = 1
            x0s = np.array([[b["x0"]] for b in bxs], dtype=float)
            km = KMeans(n_clusters=k, n_init="auto", random_state=KMEANS_RANDOM_STATE)
            labels = km.fit_predict(x0s)

            centers = km.cluster_centers_.flatten()
            order = np.argsort(centers)
            remap = {orig: new for new, orig in enumerate(order)}

            for b, lb in zip(bxs, labels):
                b["col_id"] = remap[lb]

        return boxes

    def _text_merge(self, zoomin: int = DEFAULT_ZOOMIN) -> None:
        bxs = self._assign_column(self.boxes, zoomin)

        i = 0
        while i < len(bxs) - 1:
            b = bxs[i]
            b_ = bxs[i + 1]

            if b["page_number"] != b_["page_number"] or b.get("col_id") != b_.get("col_id"):
                i += 1
                continue

            if b.get("layoutno", "0") != b_.get("layoutno", "1") or b.get("layout_type", "") in ["table", "figure", "equation"]:
                i += 1
                continue

            if abs(self._y_dis(b, b_)) < self.mean_height[bxs[i]["page_number"] - 1] / LINE_MERGE_TOLERANCE_DIVISOR:
                bxs[i]["x1"] = b_["x1"]
                bxs[i]["top"] = (b["top"] + b_["top"]) / 2
                bxs[i]["bottom"] = (b["bottom"] + b_["bottom"]) / 2
                bxs[i]["text"] += b_["text"]
                bxs.pop(i + 1)
                continue
            i += 1
        self.boxes = bxs

    def _naive_vertical_merge(self, zoomin: int = DEFAULT_ZOOMIN) -> None:
        """Join vertically adjacent boxes of the same layout block into paragraphs.

        ``zoomin`` is accepted for caller parity with the other merge passes and
        is not read: the merge compares point coordinates only.
        """
        bxs = self.boxes
        grouped: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for b in bxs:
            grouped[(b["page_number"], "x")].append(b)

        merged_boxes: list[dict[str, Any]] = []
        for (pg, col), bxs in grouped.items():
            bxs = sorted(bxs, key=lambda x: (x["top"], x["x0"]))
            if not bxs:
                continue

            mh = self.mean_height[pg - 1] if self.mean_height else np.median([b["bottom"] - b["top"] for b in bxs]) or DEFAULT_LINE_HEIGHT

            i = 0
            while i + 1 < len(bxs):
                b = bxs[i]
                b_ = bxs[i + 1]

                if b["page_number"] < b_["page_number"] and re.match(r"[0-9  •一—-]+$", b["text"]):
                    bxs.pop(i)
                    continue

                if not b["text"].strip():
                    bxs.pop(i)
                    continue

                if not b["text"].strip() or b.get("layoutno") != b_.get("layoutno"):
                    i += 1
                    continue

                if b_["top"] - b["bottom"] > mh * VERTICAL_MERGE_GAP_RATIO:
                    i += 1
                    continue

                overlap = max(0, min(b["x1"], b_["x1"]) - max(b["x0"], b_["x0"]))
                if overlap / max(1, min(b["x1"] - b["x0"], b_["x1"] - b_["x0"])) < VERTICAL_MERGE_OVERLAP_RATIO:
                    i += 1
                    continue

                concatting_feats = [
                    b["text"].strip()[-1] in ",;:'\"，、‘“；：-",
                    len(b["text"].strip()) > 1 and b["text"].strip()[-2] in ",;:'\"，‘“、；：",
                    b_["text"].strip() and b_["text"].strip()[0] in "。；？！?”）),，、：",
                ]
                feats = [
                    b.get("layoutno", 0) != b_.get("layoutno", 0),
                    b["text"].strip()[-1] in "。？！?",
                    self.is_english and b["text"].strip()[-1] in ".!?",
                    b["page_number"] == b_["page_number"] and b_["top"] - b["bottom"] > self.mean_height[b["page_number"] - 1] * VERTICAL_MERGE_GAP_RATIO,
                    b["page_number"] < b_["page_number"] and abs(b["x0"] - b_["x0"]) > self.mean_width[b["page_number"] - 1] * VERTICAL_MERGE_PAGEBREAK_WIDTH_RATIO,
                ]
                detach_feats = [b["x1"] < b_["x0"], b["x0"] > b_["x1"]]
                if (any(feats) and not any(concatting_feats)) or any(detach_feats):
                    i += 1
                    continue

                b["text"] = (b["text"].rstrip() + " " + b_["text"].lstrip()).strip()
                b["bottom"] = b_["bottom"]
                b["x0"] = min(b["x0"], b_["x0"])
                b["x1"] = max(b["x1"], b_["x1"])
                bxs.pop(i + 1)

            merged_boxes.extend(bxs)

        self.boxes = merged_boxes

    def _final_reading_order_merge(self, zoomin: int = DEFAULT_ZOOMIN) -> None:
        if not self.boxes:
            return

        self.boxes = self._assign_column(self.boxes, zoomin=zoomin)

        pages = defaultdict(lambda: defaultdict(list))
        for b in self.boxes:
            pg = b["page_number"]
            col = b.get("col_id", 0)
            pages[pg][col].append(b)

        for pg in pages:
            for col in pages[pg]:
                pages[pg][col].sort(key=lambda x: (x["top"], x["x0"]))

        new_boxes = []
        for pg in sorted(pages.keys()):
            for col in sorted(pages[pg].keys()):
                new_boxes.extend(pages[pg][col])

        self.boxes = new_boxes

    def _concat_downward(self, concat_between_pages: bool = True) -> None:
        self.boxes = Recognizer.sort_Y_firstly(self.boxes, 0)

    def _filter_forpages(self) -> None:
        """Drop table-of-contents pages, then pages that are OCR junk end to end."""
        if not self.boxes:
            return
        findit = False
        i = 0
        while i < len(self.boxes):
            if not re.match(r"(contents|目录|目次|table of contents|致谢|acknowledge)$", re.sub(r"( | |\u3000)+", "", self.boxes[i]["text"].lower())):
                i += 1
                continue
            findit = True
            eng = re.match(r"[0-9a-zA-Z :'.-]{5,}", self.boxes[i]["text"].strip())
            self.boxes.pop(i)
            if i >= len(self.boxes):
                break
            prefix = self.boxes[i]["text"].strip()[:3] if not eng else " ".join(self.boxes[i]["text"].strip().split()[:2])
            while not prefix:
                self.boxes.pop(i)
                if i >= len(self.boxes):
                    break
                prefix = self.boxes[i]["text"].strip()[:3] if not eng else " ".join(self.boxes[i]["text"].strip().split()[:2])
            self.boxes.pop(i)
            if i >= len(self.boxes) or not prefix:
                break
            for j in range(i, min(i + TOC_LOOKAHEAD_BOXES, len(self.boxes))):
                if not re.match(prefix, self.boxes[j]["text"]):
                    continue
                for k in range(i, j):
                    self.boxes.pop(i)
                break
        if findit:
            return

        page_dirty = [0] * len(self.page_images)
        for b in self.boxes:
            if re.search(r"(··|··|··)", b["text"]):
                page_dirty[b["page_number"] - 1] += 1
        page_dirty = set([i + 1 for i, t in enumerate(page_dirty) if t > TOC_DIRTY_PAGE_MARKS])
        if not page_dirty:
            return
        i = 0
        while i < len(self.boxes):
            if self.boxes[i]["page_number"] in page_dirty:
                self.boxes.pop(i)
                continue
            i += 1

    def _merge_with_same_bullet(self) -> None:
        i = 0
        while i + 1 < len(self.boxes):
            b = self.boxes[i]
            b_ = self.boxes[i + 1]
            if not b["text"].strip():
                self.boxes.pop(i)
                continue
            if not b_["text"].strip():
                self.boxes.pop(i + 1)
                continue

            if (
                b["text"].strip()[0] != b_["text"].strip()[0]
                or b["text"].strip()[0].lower() in set("qwertyuopasdfghjklzxcvbnm")
                or rag_tokenizer.is_chinese(b["text"].strip()[0])
                or b["top"] > b_["bottom"]
            ):
                i += 1
                continue
            b_["text"] = b["text"] + "\n" + b_["text"]
            b_["x0"] = min(b["x0"], b_["x0"])
            b_["x1"] = max(b["x1"], b_["x1"])
            b_["top"] = b["top"]
            self.boxes.pop(i)

    def _extract_table_figure(self, need_image: bool, ZM: int, return_html: bool, need_position: bool, separate_tables_figures: bool = False) -> Any:
        tables: dict[str, list[dict[str, Any]]] = {}
        figures: dict[str, list[dict[str, Any]]] = {}
        i = 0
        lst_lout_no = ""
        nomerge_lout_no = []
        while i < len(self.boxes):
            if "layoutno" not in self.boxes[i]:
                i += 1
                continue
            lout_no = str(self.boxes[i]["page_number"]) + "-" + str(self.boxes[i]["layoutno"])
            if TableStructureRecognizer.is_caption(self.boxes[i]) or self.boxes[i]["layout_type"] in ["table caption", "title", "figure caption", "reference"]:
                nomerge_lout_no.append(lst_lout_no)
            if self.boxes[i]["layout_type"] == "table":
                if re.match(r"(数据|资料|图表)*来源[:： ]", self.boxes[i]["text"]):
                    self.boxes.pop(i)
                    continue
                if lout_no not in tables:
                    tables[lout_no] = []
                tables[lout_no].append(self.boxes[i])
                self.boxes.pop(i)
                lst_lout_no = lout_no
                continue
            if need_image and self.boxes[i]["layout_type"] == "figure":
                if re.match(r"(数据|资料|图表)*来源[:： ]", self.boxes[i]["text"]):
                    self.boxes.pop(i)
                    continue
                if lout_no not in figures:
                    figures[lout_no] = []
                figures[lout_no].append(self.boxes[i])
                self.boxes.pop(i)
                lst_lout_no = lout_no
                continue
            i += 1

        nomerge_lout_no = set(nomerge_lout_no)
        tbls = sorted([(k, bxs) for k, bxs in tables.items()], key=lambda x: (x[1][0]["top"], x[1][0]["x0"]))

        i = len(tbls) - 1
        while i - 1 >= 0:
            k0, bxs0 = tbls[i - 1]
            k, bxs = tbls[i]
            i -= 1
            if k0 in nomerge_lout_no or bxs[0]["page_number"] == bxs0[0]["page_number"] or bxs[0]["page_number"] - bxs0[0]["page_number"] > 1:
                continue
            mh = self.mean_height[bxs[0]["page_number"] - 1]
            if self._y_dis(bxs0[-1], bxs[0]) > mh * TABLE_STITCH_MAX_Y_DIS_RATIO:
                continue
            tables[k0].extend(tables[k])
            del tables[k]

        def x_overlapped(a: dict[str, Any], b: dict[str, Any]) -> bool:
            return not any([a["x1"] < b["x0"], a["x0"] > b["x1"]])

        i = 0
        while i < len(self.boxes):
            c = self.boxes[i]
            if not TableStructureRecognizer.is_caption(c):
                i += 1
                continue

            def nearest(tbls: dict[str, list[dict[str, Any]]]) -> tuple[str, float]:
                nonlocal c
                mink = ""
                minv = float("inf")
                for k, bxs in tbls.items():
                    for b in bxs:
                        if b.get("layout_type", "").find("caption") >= 0:
                            continue
                        y_dis = self._y_dis(c, b)
                        x_dis = self._x_dis(c, b) if not x_overlapped(c, b) else 0
                        dis = y_dis * y_dis + x_dis * x_dis
                        if dis < minv:
                            mink = k
                            minv = dis
                return mink, minv

            tk, tv = nearest(tables)
            fk, fv = nearest(figures)
            if tv < fv and tk:
                tables[tk].insert(0, c)
                logging.debug("TABLE:" + self.boxes[i]["text"] + "; Cap: " + tk)
            elif fk:
                figures[fk].insert(0, c)
                logging.debug("FIGURE:" + self.boxes[i]["text"] + "; Cap: " + tk)
            self.boxes.pop(i)

        def cropout(bxs: list[dict[str, Any]], ltype: str, poss: list[Any]) -> Any:
            nonlocal ZM
            max_page_index = len(self.page_images) - 1

            def local_page_index(page_number: int) -> int:
                idx = page_number - 1 if page_number > 0 else 0
                if idx > max_page_index and self.page_from:
                    idx = page_number - 1 - self.page_from
                return idx

            pn = set()
            for b in bxs:
                idx = local_page_index(b["page_number"])
                if 0 <= idx <= max_page_index:
                    pn.add(idx)

            if not pn:
                return None

            if len(pn) < 2:
                pn = list(pn)[0]
                ht = self.page_cum_height[pn]
                b = {"x0": np.min([b["x0"] for b in bxs]), "top": np.min([b["top"] for b in bxs]) - ht, "x1": np.max([b["x1"] for b in bxs]), "bottom": np.max([b["bottom"] for b in bxs]) - ht}
                louts = [layout for layout in self.page_layout[pn] if layout["type"] == ltype]
                ii = Recognizer.find_overlapped(b, louts, naive=True)
                if ii is not None:
                    b = louts[ii]

                left, top, right, bott = b["x0"], b["top"], b["x1"], b["bottom"]
                if right < left:
                    right = left + 1
                poss.append((pn + self.page_from, left, right, top, bott))
                return self.page_images[pn].crop((left * ZM, top * ZM, right * ZM, bott * ZM))
            pn = {}
            for b in bxs:
                p = local_page_index(b["page_number"])
                if 0 <= p <= max_page_index:
                    if p not in pn:
                        pn[p] = []
                    pn[p].append(b)
            pn = sorted(pn.items(), key=lambda x: x[0])
            imgs = [cropout(arr, ltype, poss) for p, arr in pn]
            imgs = [img for img in imgs if img is not None]
            if not imgs:
                return None
            pic = Image.new("RGB", (int(np.max([i.size[0] for i in imgs])), int(np.sum([m.size[1] for m in imgs]))), IMAGE_CANVAS_BACKGROUND)
            height = 0
            for img in imgs:
                pic.paste(img, (0, int(height)))
                height += img.size[1]
            return pic

        res = []
        positions = []
        figure_results = []
        figure_positions = []
        for k, bxs in figures.items():
            if not bxs:
                continue
            txt = "\n".join([b["text"] for b in bxs if b.get("text")])

            poss = []
            if separate_tables_figures:
                img = cropout(bxs, "figure", poss)
                if img is None:
                    continue
                figure_results.append((img, [txt] if txt else [""]))
                figure_positions.append(poss)
            else:
                img = cropout(bxs, "figure", poss)
                if img is None:
                    continue
                res.append((img, [txt] if txt else [""]))
                positions.append(poss)

        for k, bxs in tables.items():
            if not bxs:
                continue
            bxs = Recognizer.sort_Y_firstly(bxs, np.mean([(b["bottom"] - b["top"]) / 2 for b in bxs]))

            poss = []
            img = cropout(bxs, "table", poss)
            if img is None:
                continue
            res.append((img, self.tbl_det.construct_table(bxs, html=return_html, is_english=self.is_english)))
            positions.append(poss)

        if separate_tables_figures:
            assert len(positions) + len(figure_positions) == len(res) + len(figure_results)
            if need_position:
                return list(zip(res, positions)), list(zip(figure_results, figure_positions))
            else:
                return res, figure_results
        else:
            assert len(positions) == len(res)
            if need_position:
                return list(zip(res, positions))
            else:
                return res

    def proj_match(self, line: str) -> int | None:
        if len(line) <= 2 or re.match(r"[0-9 ().,%%+/-]+$", line):
            return False
        for p, j in [
            (r"第[零一二三四五六七八九十百]+章", 1),
            (r"第[零一二三四五六七八九十百]+[条节]", 2),
            (r"[零一二三四五六七八九十百]+[、  ]", 3),
            (r"[\(（][零一二三四五六七八九十百]+[）\)]", 4),
            (r"[0-9]+(、|\.[  ]|\.[^0-9])", 5),
            (r"[0-9]+\.[0-9]+(、|[.  ]|[^0-9])", 6),
            (r"[0-9]+\.[0-9]+\.[0-9]+(、|[  ]|[^0-9])", 7),
            (r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+(、|[ {]|[^0-9])", 8),
            (r".{,48}[：:?？]$", 9),
            (r"[0-9]+）", 10),
            (r"[\(（][0-9]+[）\)]", 11),
            (r"[零一二三四五六七八九十百]+是", 12),
            (r"[⚫•➢✓]", 12),
        ]:
            if re.match(p, line):
                return j
        return

    def _line_tag(self, bx: dict[str, Any], ZM: int) -> str:
        pn = [bx["page_number"]]
        top = bx["top"] - self.page_cum_height[pn[0] - 1]
        bott = bx["bottom"] - self.page_cum_height[pn[0] - 1]
        page_images_cnt = len(self.page_images)
        if pn[-1] - 1 >= page_images_cnt:
            return ""
        while bott * ZM > self.page_images[pn[-1] - 1].size[1]:
            bott -= self.page_images[pn[-1] - 1].size[1] / ZM
            pn.append(pn[-1] + 1)
            if pn[-1] - 1 >= page_images_cnt:
                return ""

        return "@@{}\t{:.1f}\t{:.1f}\t{:.1f}\t{:.1f}##".format("-".join([str(p) for p in pn]), bx["x0"], bx["x1"], top, bott)

    def __filterout_scraps(self, boxes: list[dict[str, Any]], ZM: int) -> str:
        """Keep the useful lines of ``boxes`` and tag each with its position.

        Scraps are the short fragments a layout model could not attribute to a
        block; ``dfs`` walks the run they belong to and the run is kept only when
        it looks like a real line (projected like a heading, or wide enough).
        """

        def width(b: dict[str, Any]) -> float:
            return b["x1"] - b["x0"]

        def height(b: dict[str, Any]) -> float:
            return b["bottom"] - b["top"]

        def usefull(b: dict[str, Any]) -> bool:
            if b.get("layout_type"):
                return True
            if width(b) > self.page_images[b["page_number"] - 1].size[0] / ZM / LINE_MERGE_TOLERANCE_DIVISOR:
                return True
            if b["bottom"] - b["top"] > self.mean_height[b["page_number"] - 1]:
                return True
            return False

        res = []
        while boxes:
            lines = []
            widths = []
            pw = self.page_images[boxes[0]["page_number"] - 1].size[0] / ZM
            mh = self.mean_height[boxes[0]["page_number"] - 1]
            mj = self.proj_match(boxes[0]["text"]) or boxes[0].get("layout_type", "") == "title"

            def dfs(line: dict[str, Any], st: int) -> None:
                nonlocal mh, pw, lines, widths
                lines.append(line)
                widths.append(width(line))
                mmj = self.proj_match(line["text"]) or line.get("layout_type", "") == "title"
                for i in range(st + 1, min(st + SCRAP_LOOKAHEAD_LINES, len(boxes))):
                    if (boxes[i]["page_number"] - line["page_number"]) > 0:
                        break
                    if not mmj and self._y_dis(line, boxes[i]) >= SCRAP_GAP_LINES * mh and height(line) < SCRAP_MAX_HEAD_HEIGHT_RATIO * mh:
                        break

                    if not usefull(boxes[i]):
                        continue
                    if mmj or (self._x_dis(boxes[i], line) < pw / SCRAP_X_ALIGN_DIVISOR):
                        dfs(boxes[i], i)
                        boxes.pop(i)
                        break

            try:
                if usefull(boxes[0]):
                    dfs(boxes[0], 0)
                else:
                    logging.debug("WASTE: " + boxes[0]["text"])
            except Exception:
                # A malformed box must not lose the rest of the page: the run
                # collected so far is still emitted below.
                logging.exception("scrap collection failed for %r; emitting the lines collected so far", boxes[0].get("text", ""))
            boxes.pop(0)
            mw = np.mean(widths)
            if mj or mw / pw >= SCRAP_MIN_WIDTH_RATIO or mw > SCRAP_MAX_WIDTH:
                res.append("\n".join([c["text"] + self._line_tag(c, ZM) for c in lines]))
            else:
                logging.debug("REMOVED: " + "<<".join([c["text"] for c in lines]))

        return "\n\n".join(res)

    @staticmethod
    def total_page_number(fnm: str | bytes, binary: bytes | None = None) -> int | None:
        """Page count of ``fnm``; ``None`` when the file cannot be read at all.

        The handle is closed on every path, including the failure path: this runs
        once per document, so a batch import of unreadable files used to leak one
        pdfplumber handle (and its parsed object graph) per file. The lock still
        covers exactly what it covered before — opening — so concurrency is
        unchanged.
        """
        pdf = None
        try:
            with sys.modules[LOCK_KEY_pdfplumber]:
                pdf = pdfplumber.open(fnm) if not binary else pdfplumber.open(BytesIO(binary))
            return len(pdf.pages)
        except PDF_READ_ERRORS:
            logging.exception("total_page_number: %s is not a readable PDF", fnm)
            return None
        except Exception:
            logging.exception("total_page_number: unexpected failure for %s", fnm)
            return None
        finally:
            if pdf is not None:
                try:
                    pdf.close()
                except Exception:
                    logging.exception("total_page_number: closing the handle for %s failed", fnm)

    def __images__(self, fnm: str | bytes, zoomin: int = DEFAULT_ZOOMIN, page_from: int = 0, page_to: int = MAXIMUM_PAGE_NUMBER, callback: Any = None) -> None:
        self.lefted_chars = []
        self.mean_height = []
        self.mean_width = []
        self.boxes = []
        self.garbages = {}
        self.page_cum_height = [0]
        self.page_layout = []
        self.page_from = page_from
        start = timer()
        try:
            with sys.modules[LOCK_KEY_pdfplumber]:
                with pdfplumber.open(fnm) if isinstance(fnm, str) else pdfplumber.open(BytesIO(fnm)) as pdf:
                    self.pdf = pdf
                    self.page_images = [p.to_image(resolution=PDF_RENDER_DPI * zoomin, antialias=True).annotated for i, p in enumerate(self.pdf.pages[page_from:page_to])]

                    try:
                        self.page_chars = [[c for c in page.dedupe_chars().chars if self._has_color(c)] for page in self.pdf.pages[page_from:page_to]]
                    except PDF_READ_ERRORS:
                        # One page whose character stream cannot be decoded must not
                        # cost the whole document: fall back to OCR text for every
                        # page and log which window failed.
                        logging.exception("Failed to extract characters for pages %s-%s; using OCR text", page_from, page_to)
                        self.page_chars = [[] for _ in range(len(self.page_images))]

                    for pi, page_ch in enumerate(self.page_chars):
                        if not page_ch:
                            continue
                        sample = page_ch if len(page_ch) <= GARBLED_PAGE_SAMPLE_CHARS else page_ch[:GARBLED_PAGE_SAMPLE_CHARS]
                        sample_text = "".join(c.get("text", "") for c in sample)
                        if self._is_garbled_text(sample_text, threshold=GARBLED_PAGE_THRESHOLD):
                            logging.warning(
                                "Page %d: pdfplumber extracted mostly garbled characters (%d chars), clearing to use OCR fallback.",
                                page_from + pi + 1,
                                len(page_ch),
                            )
                            self.page_chars[pi] = []
                            continue
                        if self._is_garbled_by_font_encoding(page_ch):
                            logging.warning(
                                "Page %d: detected font-encoding garbled text (subset fonts with no CJK output, %d chars), clearing to use OCR fallback.",
                                page_from + pi + 1,
                                len(page_ch),
                            )
                            self.page_chars[pi] = []

                    self.total_page = len(self.pdf.pages)

        except PDF_READ_ERRORS:
            # The document could not be opened or read as a PDF. Leaving
            # ``page_images`` unset and reporting it lets the caller decide
            # between an empty result and an error, which is what happened before
            # this handler existed.
            logging.exception("RAGFlowPdfParser __images__: %s is not a readable PDF", fnm)
        except Exception:
            logging.exception("RAGFlowPdfParser __images__: unexpected failure for %s", fnm)
        logging.info(f"__images__ dedupe_chars cost {timer() - start}s")

        logging.debug("Images converted.")
        # Deterministic sample (see ``_evenly_spaced``): the document's language
        # must be a property of the document, not of the RNG state of the run that
        # happened to parse it.
        self.is_english = [re.search(IS_ENGLISH_PATTERN, "".join(c["text"] for c in _evenly_spaced(self.page_chars[i], IS_ENGLISH_SAMPLE_CHARS))) for i in range(len(self.page_chars))]
        if sum([1 if e else 0 for e in self.is_english]) > len(self.page_images) / 2:
            self.is_english = True
        else:
            self.is_english = False

        async def __img_ocr(i: int, id: int, img: Any, chars: list[dict[str, Any]], limiter: Any) -> None:
            self._insert_word_spaces(chars)

            if limiter:
                async with limiter:
                    await thread_pool_exec(self.__ocr, i + 1, img, chars, zoomin, id)
            else:
                self.__ocr(i + 1, img, chars, zoomin, id)

            if callback and i % OCR_PROGRESS_EVERY_PAGES == OCR_PROGRESS_EVERY_PAGES - 1:
                callback((i + 1) * OCR_PROGRESS_SHARE / len(self.page_images))

        async def __img_ocr_launcher() -> None:
            def __ocr_preprocess() -> list[dict[str, Any]]:
                chars = self.page_chars[i] if not self.is_english else []
                self.mean_height.append(np.median(sorted([c["height"] for c in chars])) if chars else 0)
                self.mean_width.append(np.median(sorted([c["width"] for c in chars])) if chars else 8)
                self.page_cum_height.append(img.size[1] / zoomin)
                return chars

            if self.parallel_limiter:
                tasks = []
                for i, img in enumerate(self.page_images):
                    chars = __ocr_preprocess()
                    semaphore = self.parallel_limiter[i % settings.PARALLEL_DEVICES]

                    async def wrapper(i=i, img=img, chars=chars, semaphore=semaphore):
                        await __img_ocr(i, i % settings.PARALLEL_DEVICES, img, chars, semaphore)

                    tasks.append(asyncio.create_task(wrapper()))
                    await asyncio.sleep(0)

                try:
                    await asyncio.gather(*tasks, return_exceptions=False)
                except Exception:
                    # Cancel the siblings, drain them, then re-raise: the first
                    # failure is the one worth reporting, with its stack.
                    logging.exception("Error in OCR")
                    for t in tasks:
                        t.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
                    raise
            else:
                for i, img in enumerate(self.page_images):
                    chars = __ocr_preprocess()
                    await __img_ocr(i, 0, img, chars, None)

        start = timer()
        asyncio.run(__img_ocr_launcher())
        logging.info(f"__images__ {len(self.page_images)} pages cost {timer() - start}s")

        if not self.is_english and not any([c for c in self.page_chars]) and self.boxes:
            bxes = [b for bxs in self.boxes for b in bxs]
            self.is_english = re.search(IS_ENGLISH_BOX_PATTERN, "".join(b["text"] for b in _evenly_spaced(bxes, IS_ENGLISH_SAMPLE_BOXES)))

        logging.debug(f"Is it English: {self.is_english}")
        self.page_cum_height = np.cumsum(self.page_cum_height)
        assert len(self.page_cum_height) == len(self.page_images) + 1
        if len(self.boxes) == 0 and zoomin < MAX_ZOOMIN_RETRY:
            self.__images__(fnm, zoomin * ZOOMIN_RETRY_FACTOR, page_from, page_to, callback)

    def __call__(self, fnm: str | bytes, need_image: bool = True, zoomin: int = DEFAULT_ZOOMIN, return_html: bool = False, auto_rotate_tables: bool | None = None, **kwargs: Any) -> tuple[str, Any]:
        """
        Parse a PDF file.

        Args:
            fnm: PDF file path or binary content
            need_image: Whether to extract images
            zoomin: Zoom factor
            return_html: Whether to return tables in HTML format
            auto_rotate_tables: Whether to enable auto orientation correction for tables.
            **kwargs: Extra parameters passed from upstream (e.g., domain, parser_config)
        """
        self.outlines = extract_pdf_outlines(fnm)
        self.__images__(fnm, zoomin)
        self._layouts_rec(zoomin)
        self._table_transformer_job(zoomin, auto_rotate=auto_rotate_tables)
        self._text_merge()
        self._concat_downward()
        self._filter_forpages()
        tbls = self._extract_table_figure(need_image, zoomin, return_html, False)
        return self.__filterout_scraps(deepcopy(self.boxes), zoomin), tbls

    def parse_into_bboxes(self, fnm: str | bytes, callback: Any = None, zoomin: int = DEFAULT_ZOOMIN, from_page: int = 0, to_page: int = MAXIMUM_PAGE_NUMBER) -> list[dict[str, Any]]:
        self.outlines = extract_pdf_outlines(fnm)
        batch_size = max(1, int(os.getenv("PDF_PARSER_PAGE_BATCH_SIZE", "50")))
        if isinstance(fnm, str):
            total_pages = self.total_page_number(fnm)
        else:
            total_pages = self.total_page_number(fnm, binary=fnm)

        if total_pages is None:
            effective_to_page = to_page
            logging.warning("parse_into_bboxes: total_page_number returned None; using caller-supplied to_page=%s", to_page)
        else:
            effective_to_page = min(to_page, total_pages)

        if effective_to_page - from_page <= batch_size:
            self.__images__(fnm, zoomin, page_from=from_page, page_to=effective_to_page, callback=callback)
            return self._parse_loaded_window_into_bboxes(zoomin, callback=callback)

        logging.info("parse_into_bboxes uses chunk mode: from_page=%s, effective_to_page=%s, batch_size=%s", from_page, effective_to_page, batch_size)
        all_boxes = []
        start = timer()
        for page_from in range(from_page, effective_to_page, batch_size):
            page_to = min(page_from + batch_size, effective_to_page)
            self.__images__(fnm, zoomin, page_from=page_from, page_to=page_to, callback=None)
            chunk_boxes = self._parse_loaded_window_into_bboxes(zoomin)
            all_boxes.extend(self._to_global_boxes(chunk_boxes))
            if callback:
                callback((page_to - from_page) / max(1, effective_to_page - from_page), f"Structured: {page_to}/{effective_to_page} pages")

        logging.info("parse_into_bboxes chunk mode cost %.2fs", timer() - start)
        return all_boxes

    def _parse_loaded_window_into_bboxes(self, zoomin: int = DEFAULT_ZOOMIN, callback: Any = None) -> list[dict[str, Any]]:
        start = timer()
        self._layouts_rec(zoomin)
        if callback:
            callback(0.63, "Layout analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._table_transformer_job(zoomin)
        if callback:
            callback(0.83, "Table analysis ({:.2f}s)".format(timer() - start))

        start = timer()
        self._text_merge()
        self._concat_downward()
        self._naive_vertical_merge(zoomin)
        if callback:
            callback(0.92, "Text merged ({:.2f}s)".format(timer() - start))

        start = timer()
        tbls, figs = self._extract_table_figure(True, zoomin, True, True, True)

        def insert_table_figures(tbls_or_figs: list[Any], layout_type: str) -> None:
            def min_rectangle_distance(rect1: tuple[Any, ...], rect2: tuple[Any, ...]) -> float:
                pn1, left1, right1, top1, bottom1 = rect1
                pn2, left2, right2, top2, bottom2 = rect2
                if right1 >= left2 and right2 >= left1 and bottom1 >= top2 and bottom2 >= top1:
                    return 0
                dx = left2 - right1 if right1 < left2 else (left1 - right2 if right2 < left1 else 0)
                dy = top2 - bottom1 if bottom1 < top2 else (top1 - bottom2 if bottom2 < top1 else 0)
                return math.sqrt(dx * dx + dy * dy)

            for (img, txt), poss in tbls_or_figs:
                local_poss = []
                for pn, left, right, top, bott in poss:
                    local_pn = pn - self.page_from
                    if 0 <= local_pn < len(self.page_cum_height) - 1:
                        local_poss.append((local_pn, left, right, top, bott))
                    else:
                        logging.debug(f"Skip out-of-range table/figure position pn={pn}, page_from={self.page_from}")
                if not local_poss:
                    logging.debug("No valid local positions for table/figure; skip insertion.")
                    continue

                if isinstance(txt, list):
                    txt = "\n".join(txt)
                pn, left, right, top, bott = local_poss[0]
                insert_at = len(self.boxes)
                bboxes = [(i, (b["page_number"], b["x0"], b["x1"], b["top"], b["bottom"])) for i, b in enumerate(self.boxes)]
                if bboxes:
                    dists = [
                        (min_rectangle_distance((cand_pn, cand_left, cand_right, cand_top + self.page_cum_height[cand_pn], cand_bott + self.page_cum_height[cand_pn]), rect), i)
                        for i, rect in bboxes
                        for cand_pn, cand_left, cand_right, cand_top, cand_bott in local_poss
                    ]
                    if dists:
                        nearest_bbox_idx = int(np.argmin([dist for dist, _ in dists]))
                        insert_at, _ = bboxes[dists[nearest_bbox_idx][-1]]
                        if self.boxes[insert_at]["bottom"] < top + self.page_cum_height[pn]:
                            insert_at += 1
                else:
                    logging.debug("No text boxes available; append %s block directly.", layout_type)
                self.boxes.insert(
                    insert_at,
                    {
                        "page_number": pn + 1,
                        "x0": left,
                        "x1": right,
                        "top": top + self.page_cum_height[pn],
                        "bottom": bott + self.page_cum_height[pn],
                        "layout_type": layout_type,
                        "text": txt,
                        "image": img,
                        "positions": [[pn + 1, int(left), int(right), int(top), int(bott)]],
                    },
                )

        for b in self.boxes:
            b["position_tag"] = self._line_tag(b, zoomin)
            b["image"] = self.crop(b["position_tag"], zoomin)
            b["positions"] = [[pos[0][-1] + 1, *pos[1:]] for pos in RAGFlowPdfParser.extract_positions(b["position_tag"])]

        insert_table_figures(tbls, "table")
        insert_table_figures(figs, "figure")
        if callback:
            callback(1, "Structured ({:.2f}s)".format(timer() - start))
        return deepcopy(self.boxes)

    @staticmethod
    def _offset_position_tag(text: str, page_offset: int) -> str:
        if not text or page_offset <= 0:
            return text

        def _replace(match: re.Match) -> str:
            pages = [str(int(p) + page_offset) for p in match.group(1).split("-")]
            return f"@@{'-'.join(pages)}\t"

        return re.sub(r"@@([0-9-]+)\t", _replace, text)

    def _to_global_boxes(self, boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.page_from <= 0:
            return boxes

        for box in boxes:
            box["page_number"] = int(box.get("page_number", 1)) + self.page_from
            if isinstance(box.get("position_tag"), str):
                box["position_tag"] = self._offset_position_tag(box["position_tag"], self.page_from)
            if isinstance(box.get("positions"), list):
                box["positions"] = [[int(pos[0]) + self.page_from, *pos[1:]] if isinstance(pos, list) and len(pos) > 0 and isinstance(pos[0], (int, float)) else pos for pos in box["positions"]]
        return boxes

    @staticmethod
    def remove_tag(txt: str) -> str:
        return re.sub(r"@@[\t0-9.-]+?##", "", txt)

    @staticmethod
    def extract_positions(txt: str) -> list[tuple[list[int], float, float, float, float]]:
        poss = []
        for tag in re.findall(r"@@[0-9-]+\t[0-9.\t]+##", txt):
            pn, left, right, top, bottom = tag.strip("#").strip("@").split("\t")
            left, right, top, bottom = float(left), float(right), float(top), float(bottom)
            poss.append(([int(p) - 1 for p in pn.split("-")], left, right, top, bottom))
        return poss

    def crop(self, text: str, ZM: int = DEFAULT_ZOOMIN, need_position: bool = False) -> Any:
        """Stitch the image(s) covering the ``@@page`` tags in ``text``.

        Returns the merged image, or ``(image, positions)`` when ``need_position``
        is set, or ``None`` when there is nothing to crop.
        """
        imgs = []
        poss = self.extract_positions(text)
        if not poss:
            return (None, None) if need_position else None

        if not getattr(self, "page_images", None):
            logging.warning("crop called without page images; skipping image generation.")
            return (None, None) if need_position else None

        page_count = len(self.page_images)

        filtered_poss = []
        for pns, left, right, top, bottom in poss:
            if not pns:
                logging.warning("Empty page index list in crop; skipping this position.")
                continue
            valid_pns = [p for p in pns if 0 <= p < page_count]
            if not valid_pns:
                logging.warning(f"All page indices {pns} out of range for {page_count} pages; skipping.")
                continue
            filtered_poss.append((valid_pns, left, right, top, bottom))

        poss = filtered_poss
        if not poss:
            logging.warning("No valid positions after filtering; skip cropping.")
            return (None, None) if need_position else None

        max_width = max(np.max([right - left for (_, left, right, _, _) in poss]), CROP_MIN_WIDTH)
        GAP = CROP_GAP

        pos = poss[0]
        first_page_idx = pos[0][0]
        poss.insert(0, ([first_page_idx], pos[1], pos[2], max(0, pos[3] - CROP_CONTEXT_HEIGHT), max(pos[3] - GAP, 0)))

        pos = poss[-1]
        last_page_idx = pos[0][-1]
        if not (0 <= last_page_idx < page_count):
            logging.warning(f"Last page index {last_page_idx} out of range for {page_count} pages; skipping crop.")
            return (None, None) if need_position else None

        last_page_height = self.page_images[last_page_idx].size[1] / ZM
        poss.append(
            (
                [last_page_idx],
                pos[1],
                pos[2],
                min(last_page_height, pos[4] + GAP),
                min(last_page_height, pos[4] + CROP_CONTEXT_HEIGHT),
            )
        )

        positions = []
        for ii, (pns, left, right, top, bottom) in enumerate(poss):
            if 0 < ii < len(poss) - 1:
                right = max(left + CROP_MIN_SEGMENT_WIDTH, right)
            else:
                right = left + max_width

            bottom *= ZM
            for pn in pns[1:]:
                if 0 <= pn - 1 < page_count:
                    bottom += self.page_images[pn - 1].size[1]
                else:
                    logging.warning(f"Page index {pn}-1 out of range for {page_count} pages during crop; skipping height accumulation.")

            if not (0 <= pns[0] < page_count):
                logging.warning(f"Base page index {pns[0]} out of range for {page_count} pages during crop; skipping this segment.")
                continue

            imgs.append(self.page_images[pns[0]].crop((left * ZM, top * ZM, right * ZM, min(bottom, self.page_images[pns[0]].size[1]))))
            if 0 < ii < len(poss) - 1:
                positions.append((pns[0] + self.page_from, left, right, top, min(bottom, self.page_images[pns[0]].size[1]) / ZM))

            bottom -= self.page_images[pns[0]].size[1]

            for pn in pns[1:]:
                if not (0 <= pn < page_count):
                    logging.warning(f"Page index {pn} out of range for {page_count} pages during crop; skipping this page.")
                    continue
                imgs.append(self.page_images[pn].crop((left * ZM, 0, right * ZM, min(bottom, self.page_images[pn].size[1]))))
                if 0 < ii < len(poss) - 1:
                    positions.append((pn + self.page_from, left, right, 0, min(bottom, self.page_images[pn].size[1]) / ZM))

                bottom -= self.page_images[pn].size[1]

        if not imgs:
            return (None, None) if need_position else None

        total_height = sum(img.size[1] for img in imgs)
        max_img_width = max(img.size[0] for img in imgs)

        merged_image = Image.new("RGB", (int(max_img_width), int(total_height)), IMAGE_CANVAS_BACKGROUND)

        current_y = 0
        for img in imgs:
            merged_image.paste(img, (0, int(current_y)))
            current_y += img.size[1]

        if need_position:
            return merged_image, positions

        return merged_image

    def get_position(self, bx: dict[str, Any], ZM: int) -> list[tuple[int, float, float, float, float]]:
        poss = []
        pn = bx["page_number"]
        top = bx["top"] - self.page_cum_height[pn - 1]
        bott = bx["bottom"] - self.page_cum_height[pn - 1]
        poss.append((pn, bx["x0"], bx["x1"], top, min(bott, self.page_images[pn - 1].size[1] / ZM)))
        while bott * ZM > self.page_images[pn - 1].size[1]:
            bott -= self.page_images[pn - 1].size[1] / ZM
            top = 0
            pn += 1
            poss.append((pn, bx["x0"], bx["x1"], top, min(bott, self.page_images[pn - 1].size[1] / ZM)))
        return poss


class PlainParser:
    def __call__(self, filename: str | bytes, from_page: int = 0, to_page: int = MAXIMUM_PAGE_NUMBER, **kwargs: Any) -> tuple[list[tuple[str, str]], list]:
        """Read ``filename`` page by page with pypdf and return ``(lines, [])``.

        The reader is closed by the ``with`` block. pypdf keeps the whole parsed
        object graph (xref, trailer, resolved objects) alive on the reader, so
        without this a batch import holds one document's worth of objects per file
        for as long as the caller keeps the parser.
        """
        lines: list[str] = []
        try:
            with pdf2_read(filename if isinstance(filename, str) else BytesIO(filename)) as pdf:
                self.pdf = pdf
                for page in pdf.pages[from_page:to_page]:
                    lines.extend([t for t in page.extract_text().split("\n")])
        except PDF_READ_ERRORS:
            logging.exception("PlainParser: %s is not a readable PDF", filename)
        except Exception:
            logging.exception("PlainParser: unexpected failure for %s", filename)
        self.outlines = extract_pdf_outlines(filename)

        return [(line, "") for line in lines], []

    def crop(self, ck: str, need_position: bool) -> Any:
        raise NotImplementedError

    @staticmethod
    def remove_tag(txt: str) -> str:
        raise NotImplementedError


class VisionParser(RAGFlowPdfParser):
    def __init__(self, vision_model: Any, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.vision_model = vision_model
        self.outlines = []

    def __images__(self, fnm: str | bytes, zoomin: int = DEFAULT_ZOOMIN, page_from: int = 0, page_to: int = MAXIMUM_PAGE_NUMBER, callback: Any = None) -> None:
        """Render the requested page window to images for the vision model.

        The handle is opened and closed inside one ``with``: this parser renders
        EVERY page of the window into a PIL image and keeps them in
        ``self.page_images``, so the pdfplumber handle itself is dead weight after
        the loop — and an unclosed one leaks a file descriptor per document plus
        the page/stream graph behind it, which is what a parallel ingest of a
        large batch exhausts first.
        """
        try:
            with sys.modules[LOCK_KEY_pdfplumber], pdfplumber.open(fnm) if isinstance(fnm, str) else pdfplumber.open(BytesIO(fnm)) as pdf:
                self.pdf = pdf
                self.page_images = [p.to_image(resolution=PDF_RENDER_DPI * zoomin).annotated for i, p in enumerate(pdf.pages[page_from:page_to])]
                self.total_page = len(pdf.pages)
        except PDF_READ_ERRORS:
            self.page_images = None
            self.total_page = 0
            logging.exception("VisionParser __images__: %s is not a readable PDF", fnm)
        except Exception:
            self.page_images = None
            self.total_page = 0
            logging.exception("VisionParser __images__: unexpected failure for %s", fnm)

    def __call__(self, filename: str | bytes, from_page: int = 0, to_page: int = MAXIMUM_PAGE_NUMBER, **kwargs: Any) -> tuple[list[tuple[str, str]], list]:
        callback = kwargs.get("callback", lambda prog, msg: None)
        zoomin = kwargs.get("zoomin", DEFAULT_ZOOMIN)
        self.__images__(fnm=filename, zoomin=zoomin, page_from=from_page, page_to=to_page, callback=callback)

        total_pdf_pages = self.total_page
        start_page = max(0, from_page)
        end_page = min(to_page, total_pdf_pages)

        # Resolve the domain once per call (never per page).
        domain, reason = resolve_domain_with_confidence(kwargs, context_text=str(filename))
        logging.info(f"[VisionParser] domain_resolution domain={domain!r} reason={reason}")

        all_docs = []

        for idx, img_binary in enumerate(self.page_images or []):
            pdf_page_num = from_page + idx  # 0-based
            if pdf_page_num < start_page or pdf_page_num >= end_page:
                continue

            from rag.app.picture import vision_llm_chunk as picture_vision_llm_chunk

            prompt = vision_llm_describe_prompt(page=pdf_page_num + 1)

            # Inject the domain instruction before the vision LLM call.
            if not isinstance(prompt, str):
                logging.warning("[VisionParser] prompt is not str; skipping domain injection")
            else:
                prompt = inject_domain_instruction(prompt, domain, figure_idx=idx, reason=reason)

            text = picture_vision_llm_chunk(
                binary=img_binary,
                vision_model=self.vision_model,
                prompt=prompt,
                callback=callback,
            )

            if kwargs.get("callback"):
                kwargs["callback"](idx * 1.0 / len(self.page_images), f"Processed: {idx + 1}/{len(self.page_images)}")

            if text:
                width, height = self.page_images[idx].size
                all_docs.append((text, f"@@{pdf_page_num + 1}\t{0.0:.1f}\t{width / zoomin:.1f}\t{0.0:.1f}\t{height / zoomin:.1f}##"))
        return all_docs, []


if __name__ == "__main__":
    pass
