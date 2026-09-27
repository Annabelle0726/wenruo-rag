#
#  Copyright 2026 The InfiniFlow Authors. All Rights Reserved.
#  Modifications Copyright 2026 线缆工业智搜平台. All Rights Reserved.
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
"""Box geometry leaves this parser as plain Python numbers.

Every box the parser builds either comes from a text layer (pdfplumber floats) or
from a model: the OCR detection network, the layout recogniser and the table
structure recogniser all hand back float32 numpy scalars. ``np.float32`` is not a
``float`` — unlike ``np.float64`` it is not even a subclass of one — so an un-cast
coordinate keeps every later subtraction in numpy's type system:

* ``deepdoc`` instruments itself with beartype, so a ``-> float`` helper that
  returns ``np.float32`` raises ``BeartypeCallHintReturnViolation``. Coming out of
  ``_concat_downward`` that aborts the whole chunking task — the cable corpus
  reported exactly this ("Method …_x_dis() return np.float32(72.33334) violates
  type hint <class 'float'>") — and inside ``__filterout_scraps``, where the
  exception is caught per line, it silently DROPS the line instead.
* the same scalars are not JSON-serialisable and would reach chunk payloads and the
  document metadata.

These tests pin the invariant that makes the annotations true — plain builtin
numbers on the way out — rather than the violation message: a type assertion fails
on the pre-fix code for the same reason production failed, and it does not depend on
the runtime checker being installed. The module is loaded the way its neighbours in
this directory load it (heavy third-party imports stubbed, real numpy kept), so the
test never needs the OCR models.
"""

import importlib.util
import logging
import re
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

pytestmark = pytest.mark.p1

ZOOMIN = 3
PAGE_SIZE = (1200, 1600)
#: One page of image height at ``ZOOMIN``: the offset ``__images__`` cumulates.
PAGE_OFFSET = PAGE_SIZE[1] / ZOOMIN

#: The value from the reported failure, as a float32 exactly as OCR hands it back.
REPORTED_VALUE = np.float32(72.33334)


def _stub_module(monkeypatch, name, **attrs):
    module = ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


def _load_pdf_parser(monkeypatch):
    """Load ``deepdoc/parser/pdf_parser.py`` with its heavy dependencies stubbed."""
    repo_root = Path(__file__).resolve().parents[4]

    _stub_module(monkeypatch, "pdfplumber")
    _stub_module(monkeypatch, "pypdf", PdfReader=object)
    _stub_module(monkeypatch, "huggingface_hub", snapshot_download=lambda **_kwargs: "")
    _stub_module(monkeypatch, "xgboost", Booster=object)
    _stub_module(monkeypatch, "sklearn")
    _stub_module(monkeypatch, "sklearn.cluster", KMeans=object)
    _stub_module(monkeypatch, "sklearn.metrics", silhouette_score=lambda *_args, **_kwargs: 0)

    common_mod = _stub_module(monkeypatch, "common")
    common_mod.__path__ = [str(repo_root / "common")]
    _stub_module(monkeypatch, "common.constants", MAXIMUM_PAGE_NUMBER=1024)
    _stub_module(monkeypatch, "common.file_utils", get_project_base_directory=lambda: str(repo_root))
    _stub_module(monkeypatch, "common.settings", PARALLEL_DEVICES=1)
    _stub_module(monkeypatch, "common.misc_utils", thread_pool_exec=lambda fn, *args, **kwargs: fn(*args, **kwargs))

    deepdoc_mod = _stub_module(monkeypatch, "deepdoc")
    deepdoc_mod.__path__ = [str(repo_root / "deepdoc")]
    parser_mod = _stub_module(monkeypatch, "deepdoc.parser")
    parser_mod.__path__ = [str(repo_root / "deepdoc" / "parser")]
    _stub_module(monkeypatch, "deepdoc.parser.utils", extract_pdf_outlines=lambda *_args, **_kwargs: [])
    _stub_module(
        monkeypatch,
        "deepdoc.vision",
        OCR=object,
        AscendLayoutRecognizer=object,
        LayoutRecognizer=object,
        Recognizer=object,
        TableStructureRecognizer=SimpleNamespace(is_caption=lambda _box: False),
    )

    rag_mod = _stub_module(monkeypatch, "rag")
    rag_mod.__path__ = [str(repo_root / "rag")]
    _stub_module(monkeypatch, "rag.nlp", rag_tokenizer=SimpleNamespace(tokenize=lambda text: text, tag=lambda _token: "n"))
    prompts_mod = _stub_module(monkeypatch, "rag.prompts")
    prompts_mod.__path__ = [str(repo_root / "rag" / "prompts")]
    _stub_module(monkeypatch, "rag.prompts.generator", vision_llm_describe_prompt="")

    module_name = "test_pdf_parser_box_geometry_module"
    module_path = repo_root / "deepdoc" / "parser" / "pdf_parser.py"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def pdf(monkeypatch):
    return _load_pdf_parser(monkeypatch)


def _parser_without_models(pdf, page_count: int = 1, mean_height: float = 20.0):
    """A parser instance with no model loaded — these tests never parse a file."""
    parser = pdf.RAGFlowPdfParser.__new__(pdf.RAGFlowPdfParser)
    parser.page_images = [SimpleNamespace(size=PAGE_SIZE) for _ in range(page_count)]
    parser.page_cum_height = [0.0] + [PAGE_OFFSET * (index + 1) for index in range(page_count)]
    parser.mean_height = [mean_height] * page_count
    parser.mean_width = [8.0] * page_count
    parser.boxes = []
    parser.page_from = 0
    parser.lefted_chars = []
    return parser


def _ocr_box(text="额定电压1kV架空绝缘导线", *, x0=60.0, x1=500.0, top=100.0, bottom=120.0, page_number=1, layout_type=None) -> dict:
    """A box shaped like the ones ``__ocr`` builds out of float32 detections."""
    box = {
        "text": text,
        "x0": np.float32(x0),
        "x1": np.float32(x1),
        "top": np.float32(top),
        "bottom": np.float32(bottom),
        "page_number": page_number,
        "chars": [],
        "R": -1,
        "in_row": 0,
    }
    if layout_type:
        box["layout_type"] = layout_type
    return box


# ---------------------------------------------------------------------------
# The cast helper
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [np.float32(72.33334), np.float64(72.33334), np.int32(72), np.int64(72), 72.5, 72])
def test_a_coordinate_is_always_returned_as_a_builtin_float(pdf, value):
    coordinate = pdf.as_coord(value)

    assert type(coordinate) is float, f"{type(coordinate).__name__} is not a builtin float"
    assert coordinate == float(value)


def test_a_float32_coordinate_keeps_its_exact_value(pdf):
    """Widening to a double is loss-free, so no coordinate moves."""
    assert pdf.as_coord(REPORTED_VALUE) == float(REPORTED_VALUE)
    assert repr(pdf.as_coord(REPORTED_VALUE)) == repr(float(REPORTED_VALUE))


def test_normalizing_a_box_casts_its_geometry_and_nothing_else(pdf):
    box = _ocr_box(layout_type="table")
    box["layoutno"] = "table-0"

    pdf.normalize_box_coords(box)

    assert all(type(box[key]) is float for key in pdf.BOX_COORD_KEYS)
    assert box["layout_type"] == "table"
    assert box["layoutno"] == "table-0"
    assert box["page_number"] == 1


def test_normalizing_a_box_tolerates_missing_geometry(pdf):
    box = {"text": "只有文字"}

    pdf.normalize_box_coords(box)

    assert box == {"text": "只有文字"}


# ---------------------------------------------------------------------------
# The helpers the feature vector and the scrap pass are built on
# ---------------------------------------------------------------------------


def test_the_reported_crash_site_returns_a_builtin_float(pdf):
    """``_x_dis(np.float32(…))`` is the documented production failure."""
    parser = _parser_without_models(pdf)
    left = _ocr_box(x0=0.0, x1=100.0)
    right = _ocr_box(x0=172.33334, x1=300.0)

    distance = parser._x_dis(left, right)

    assert type(distance) is float
    assert distance == pytest.approx(72.33334)


@pytest.mark.parametrize("helper", ["_x_dis", "_y_dis", "_RAGFlowPdfParser__char_width", "_RAGFlowPdfParser__height"])
def test_every_geometry_helper_returns_a_builtin_float_for_an_ocr_box(pdf, helper):
    parser = _parser_without_models(pdf)
    up = _ocr_box(x0=60.0, x1=500.0, top=100.0, bottom=120.0)
    down = _ocr_box(x0=60.0, x1=520.0, top=124.0, bottom=144.0)

    value = getattr(parser, helper)(up, down) if helper in ("_x_dis", "_y_dis") else getattr(parser, helper)(up)

    assert type(value) is float, f"{helper} returned {type(value).__name__}"
    assert not isinstance(value, np.generic)


def test_the_concat_features_carry_no_numpy_scalar(pdf):
    """The vector the upward/downward model is asked about, as built from OCR boxes."""
    parser = _parser_without_models(pdf)
    up = _ocr_box(x0=60.0, x1=500.0, top=100.0, bottom=120.0, layout_type="text")
    down = _ocr_box(x0=60.0, x1=520.0, top=124.0, bottom=144.0, layout_type="text")

    features = parser._updown_concat_features(up, down)

    offenders = [value for value in features if isinstance(value, np.generic)]
    assert offenders == [], f"numpy scalars in the feature vector: {offenders}"


# ---------------------------------------------------------------------------
# The passes that adopt boxes from a model
# ---------------------------------------------------------------------------


def test_the_layouter_boundary_leaves_plain_floats_and_applies_the_page_offset(pdf):
    parser = _parser_without_models(pdf, page_count=2)
    first = _ocr_box(x0=60.0, x1=500.0, top=100.0, bottom=120.0, page_number=1)
    second = _ocr_box(x0=60.0, x1=500.0, top=100.0, bottom=120.0, page_number=2)
    parser.boxes = [first, second]
    parser.layouter = lambda images, boxes, zoom, drop=True: (boxes, [[], []])

    parser._layouts_rec(ZOOMIN)

    for box in parser.boxes:
        assert all(type(box[key]) is float for key in pdf.BOX_COORD_KEYS)
    assert first["top"] == pytest.approx(float(np.float32(100.0)))
    assert second["top"] == pytest.approx(float(np.float32(100.0)) + PAGE_OFFSET)
    assert second["bottom"] == pytest.approx(float(np.float32(120.0)) + PAGE_OFFSET)
    assert second["x0"] == pytest.approx(float(np.float32(60.0)))


def test_scrapping_a_float32_page_keeps_its_lines(pdf, caplog):
    """The silent half of the bug: a violation here drops the page's text.

    ``__filterout_scraps`` collects each run of lines under a broad handler, so a
    ``width()`` that raises does not fail the parse — it empties the line. The
    assertion is on the text, and on the absence of the handler's report.
    """
    parser = _parser_without_models(pdf)
    boxes = [
        _ocr_box(text="额定电压1kV架空绝缘导线结构尺寸", layout_type="text"),
        _ocr_box(text="本表适用于交流额定电压1kV的架空绝缘导线。", top=200.0, bottom=220.0),
    ]

    with caplog.at_level(logging.ERROR):
        text = parser._RAGFlowPdfParser__filterout_scraps(boxes, ZOOMIN)

    assert "额定电压1kV架空绝缘导线结构尺寸" in text
    assert "本表适用于交流额定电压1kV的架空绝缘导线。" in text
    assert "scrap collection failed" not in caplog.text


def test_scrapped_lines_are_tagged_with_the_boxes_own_coordinates(pdf):
    parser = _parser_without_models(pdf)
    boxes = [_ocr_box(text="1kV架空绝缘导线抽检结果", layout_type="text")]

    text = parser._RAGFlowPdfParser__filterout_scraps(boxes, ZOOMIN)

    tag = re.search(r"@@([^\t#]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)\t([0-9.]+)##", text)
    assert tag, f"the line must carry a readable position tag: {text!r}"
    assert tag.group(1) == "1"
    assert [float(value) for value in tag.groups()[1:]] == [60.0, 500.0, 100.0, 120.0]
