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
import logging
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED, as_completed

from PIL import Image

from common.exceptions import TaskCanceledException
from common.constants import LLMType
from api.db.services.llm_service import LLMBundle
from api.db.joint_services.tenant_model_service import get_tenant_default_model_by_type
from common.connection_utils import timeout
from rag.app.picture import vision_llm_chunk as picture_vision_llm_chunk
from rag.prompts.generator import (
    vision_llm_figure_describe_prompt,
    vision_llm_figure_describe_prompt_with_context,
)
from rag.nlp import append_context2table_image4pdf
from rag.utils.lazy_image import ensure_pil_image, open_image_for_processing, is_image_like
from deepdoc.parser.domain_prompts import (
    inject_domain_instruction as _inject_domain_instruction,
    resolve_domain_with_confidence as _resolve_domain_with_confidence,
)


# ============================================================
# 1. Domain Auto-Inference & Prompt Injection (Conservative)
# ============================================================
# Keyword tables and helpers live in deepdoc/parser/domain_prompts.py
# (dependency-free) and are imported above as _resolve_domain_with_confidence /
# _inject_domain_instruction.


# ============================================================
# 2. Shared Helpers
# ============================================================


def _normalize_vision_language(lang):
    return lang or "English"


def vision_figure_parser_figure_data_wrapper(figures_data_without_positions):
    if not figures_data_without_positions:
        return []
    res = []
    for figure_data in figures_data_without_positions:
        img = ensure_pil_image(figure_data[1])
        if not isinstance(img, Image.Image):
            continue
        res.append(
            (
                (img, [figure_data[0]]),
                [(0, 0, 0, 0, 0)],
            )
        )
    return res


# ============================================================
# 3. DOCX Wrapper (sections/tbls)
# ============================================================


def vision_figure_parser_docx_wrapper(sections, tbls, callback=None, lang="English", **kwargs):
    """
    Enhance DOCX figures for the section/table based chunkers (Manual, Book).

    `sections` is the `(text, image)` list produced by the DOCX parser and
    `tbls` the already accumulated table chunks, returned with the vision
    enhanced figures appended. Domain resolution happens once inside
    VisionFigureParser.
    """
    lang = _normalize_vision_language(lang)
    if not sections:
        return tbls
    try:
        vision_model_config = get_tenant_default_model_by_type(kwargs["tenant_id"], LLMType.VISION)
        vision_model = LLMBundle(kwargs["tenant_id"], vision_model_config, lang=lang)
        if callback:
            callback(0.7, "Visual model detected. Attempting to enhance figure extraction...")
    except Exception:
        vision_model = None

    if vision_model:
        figures_data = vision_figure_parser_figure_data_wrapper(sections)
        try:
            docx_vision_parser = VisionFigureParser(
                vision_model=vision_model,
                figures_data=figures_data,
                lang=lang,
                **kwargs,
            )
            boosted_figures = docx_vision_parser(callback=callback)
            tbls.extend(boosted_figures)
        except TaskCanceledException:
            raise
        except Exception as e:
            if callback:
                callback(0.8, f"Visual model error: {e}. Skipping figure parsing enhancement.")
    return tbls


# ============================================================
# 4. XLSX Wrapper
# ============================================================


def vision_figure_parser_figure_xlsx_wrapper(images, callback=None, lang="English", **kwargs):
    lang = _normalize_vision_language(lang)
    tbls = []
    if not images:
        return []
    try:
        vision_model_config = get_tenant_default_model_by_type(kwargs["tenant_id"], LLMType.VISION)
        vision_model = LLMBundle(kwargs["tenant_id"], vision_model_config, lang=lang)
        if callback:
            callback(0.2, "Visual model detected. Attempting to enhance Excel image extraction...")
    except Exception:
        vision_model = None

    if vision_model:
        figures_data = [
            (
                (
                    img["image"],
                    [img["image_description"]],
                ),
                [(0, 0, 0, 0, 0)],
            )
            for img in images
        ]
        try:
            parser = VisionFigureParser(
                vision_model=vision_model,
                figures_data=figures_data,
                lang=lang,
                **kwargs,
            )
            if callback:
                callback(0.22, "Parsing images...")
            boosted_figures = parser(callback=callback)
            tbls.extend(boosted_figures)
        except TaskCanceledException:
            raise
        except Exception as e:
            if callback:
                callback(0.25, f"Excel visual model error: {e}. Skipping vision enhancement.")
    return tbls


# ============================================================
# 5. PDF Wrapper
# ============================================================


def vision_figure_parser_pdf_wrapper(tbls, callback=None, lang="English", **kwargs):
    lang = _normalize_vision_language(lang)
    if not tbls:
        return []
    sections = kwargs.get("sections")
    parser_config = kwargs.get("parser_config", {})
    context_size = max(0, int(parser_config.get("image_context_size", 0) or 0))

    try:
        vision_model_config = get_tenant_default_model_by_type(kwargs["tenant_id"], LLMType.VISION)
        vision_model = LLMBundle(kwargs["tenant_id"], vision_model_config, lang=lang)
        if callback:
            callback(0.7, "Visual model detected. Attempting to enhance figure extraction...")
    except Exception:
        vision_model = None

    if vision_model:

        def is_figure_item(item):
            return is_image_like(item[0][0]) and isinstance(item[0][1], list)

        figures_data = [item for item in tbls if is_figure_item(item)]
        figure_contexts = []
        if sections and figures_data and context_size > 0:
            figure_contexts = append_context2table_image4pdf(
                sections,
                figures_data,
                context_size,
                return_context=True,
            )
        try:
            docx_vision_parser = VisionFigureParser(
                vision_model=vision_model,
                figures_data=figures_data,
                figure_contexts=figure_contexts,
                context_size=context_size,
                lang=lang,
                **kwargs,
            )
            boosted_figures = docx_vision_parser(callback=callback)
            tbls = [item for item in tbls if not is_figure_item(item)]
            tbls.extend(boosted_figures)
        except TaskCanceledException:
            raise
        except Exception as e:
            if callback:
                callback(0.8, f"Visual model error: {e}. Skipping figure parsing enhancement.")
    return tbls


# ============================================================
# 6. DOCX Naive Wrapper (chunks/idx_lst)
# ============================================================


def vision_figure_parser_docx_wrapper_naive(chunks, idx_lst, callback=None, lang="English", **kwargs):
    lang = _normalize_vision_language(lang)
    if not chunks:
        return []

    # Single-pass domain resolution across all target chunks
    all_context = " ".join((chunks[i].get("context_above", "") + " " + chunks[i].get("context_below", "")) for i in idx_lst)
    domain, reason = _resolve_domain_with_confidence(kwargs, context_text=all_context)
    logging.info(f"[VisionFigureParser] docx wrapper resolved domain={domain!r} reason={reason}")

    try:
        vision_model_config = get_tenant_default_model_by_type(kwargs["tenant_id"], LLMType.VISION)
        vision_model = LLMBundle(kwargs["tenant_id"], vision_model_config, lang=lang)
        if callback:
            callback(0.7, "Visual model detected. Attempting to enhance figure extraction...")
    except Exception:
        vision_model = None

    if vision_model:

        @timeout(30, 3)
        def worker(idx, ck):
            img, close_after = open_image_for_processing(ck.get("image"), allow_bytes=True)
            if not isinstance(img, Image.Image):
                return idx, ""
            context_above = ck.get("context_above", "")
            context_below = ck.get("context_below", "")

            if context_above or context_below:
                prompt = vision_llm_figure_describe_prompt_with_context(
                    context_above=ck.get("context_above") + ck.get("text", ""),
                    context_below=ck.get("context_below"),
                    language=lang,
                )
                logging.info(f"[VisionFigureParser] figure={idx} context_above_len={len(context_above)} " f"context_below_len={len(context_below)} prompt=with_context")
            else:
                prompt = vision_llm_figure_describe_prompt(language=lang)
                logging.info(f"[VisionFigureParser] figure={idx} context_len=0 prompt=default")

            # Reuse pre-resolved domain/reason (zero per-image overhead)
            prompt = _inject_domain_instruction(prompt, domain, figure_idx=idx, reason=reason)

            try:
                description_text = picture_vision_llm_chunk(
                    binary=img,
                    vision_model=vision_model,
                    prompt=prompt,
                    callback=callback,
                )
                return idx, description_text
            finally:
                if close_after and isinstance(img, Image.Image):
                    try:
                        img.close()
                    except Exception:
                        pass

        executor = ThreadPoolExecutor(max_workers=10)
        pending = {executor.submit(worker, idx, chunks[idx]) for idx in idx_lst}
        try:
            while pending:
                done, pending = wait(pending, timeout=1.0, return_when=FIRST_COMPLETED)
                for future in done:
                    idx, description = future.result()
                    chunks[idx]["text"] += description
                if callback:
                    callback(0.75, "")
        except Exception:
            for f in pending:
                f.cancel()
            executor.shutdown(wait=False, cancel_futures=True)
            raise
        else:
            executor.shutdown(wait=True)


shared_executor = ThreadPoolExecutor(max_workers=10)


# ============================================================
# 7. VisionFigureParser (full class, completed)
# ============================================================


class VisionFigureParser:
    def __init__(self, vision_model, figures_data, *args, lang="English", **kwargs):
        self.vision_model = vision_model
        self.language = _normalize_vision_language(lang) or kwargs.get("lang") or "English"
        self.figure_contexts = kwargs.get("figure_contexts") or []
        self.context_size = max(0, int(kwargs.get("context_size", 0) or 0))

        # Single-pass domain resolution (uses figure_contexts as text source)
        combined_context = ""
        if self.figure_contexts:
            combined_context = " ".join((ctx[0] or "") + " " + (ctx[1] or "") for ctx in self.figure_contexts if isinstance(ctx, (tuple, list)) and len(ctx) >= 2)

        self.domain, self.domain_reason = _resolve_domain_with_confidence(kwargs, context_text=combined_context)
        logging.info(f"[VisionFigureParser] Class initialized with domain={self.domain!r} " f"reason={self.domain_reason}")

        self._extract_figures_info(figures_data)
        assert len(self.figures) == len(self.descriptions)
        assert not self.positions or (len(self.figures) == len(self.positions))

    # --------------------------------------------------------
    def _extract_figures_info(self, figures_data):
        self.figures = []
        self.descriptions = []
        self.positions = []

        for item in figures_data:
            # With position: ((img, [desc]), [(x, y, w, h, page), ...])
            if len(item) == 2 and isinstance(item[0], tuple) and len(item[0]) == 2 and isinstance(item[1], list) and isinstance(item[1][0], tuple) and len(item[1][0]) == 5:
                img_desc = item[0]
                img = ensure_pil_image(img_desc[0])
                if img is None:
                    continue
                assert len(img_desc) == 2 and isinstance(img_desc[1], list), "Should be (figure, [description])"
                self.figures.append(img)
                self.descriptions.append(img_desc[1])
                self.positions.append(item[1])
            else:
                img = ensure_pil_image(item[0])
                if img is None:
                    continue
                assert len(item) == 2 and isinstance(item[1], list), f"Unexpected form of figure data: get {len(item)=}, {item=}"
                self.figures.append(img)
                self.descriptions.append(item[1])

    # --------------------------------------------------------
    def _assemble(self):
        self.assembled = []
        self.has_positions = len(self.positions) != 0
        for i in range(len(self.figures)):
            figure = self.figures[i]
            desc = self.descriptions[i]
            pos = self.positions[i] if self.has_positions else None

            figure_desc = (figure, desc)
            if pos is not None:
                self.assembled.append((figure_desc, pos))
            else:
                self.assembled.append((figure_desc,))

        return self.assembled

    # --------------------------------------------------------
    def __call__(self, **kwargs):
        callback = kwargs.get("callback") or (lambda prog, msg: None)

        @timeout(30, 3)
        def process(figure_idx, figure_binary):
            context_above = ""
            context_below = ""
            if figure_idx < len(self.figure_contexts):
                context_above, context_below = self.figure_contexts[figure_idx]

            if context_above or context_below:
                prompt = vision_llm_figure_describe_prompt_with_context(
                    context_above=context_above,
                    context_below=context_below,
                    language=self.language,
                )
                logging.info(
                    f"[VisionFigureParser] figure={figure_idx} context_size={self.context_size} "
                    f"context_above_len={len(context_above)} "
                    f"context_below_len={len(context_below)} prompt=with_context"
                )
            else:
                prompt = vision_llm_figure_describe_prompt(language=self.language)
                logging.info(f"[VisionFigureParser] figure={figure_idx} context_size={self.context_size} " f"context_len=0 prompt=default")

            # Reuse pre-resolved domain/reason
            prompt = _inject_domain_instruction(prompt, self.domain, figure_idx=figure_idx, reason=self.domain_reason)

            description_text = picture_vision_llm_chunk(
                binary=figure_binary,
                vision_model=self.vision_model,
                prompt=prompt,
                callback=callback,
            )
            return figure_idx, description_text

        # ----------------------------------------------------
        # Original upstream left this section empty. We complete
        # it by submitting all figures in parallel and merging
        # the resulting descriptions back into self.descriptions.
        # ----------------------------------------------------
        if not self.figures:
            self._assemble()
            return self.assembled

        max_workers = min(len(self.figures), 10) or 1
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_idx = {executor.submit(process, i, fig): i for i, fig in enumerate(self.figures)}

            for future in as_completed(future_to_idx):
                idx = future_to_idx[future]
                try:
                    _, description = future.result()
                    if description:
                        # Append the vision-generated description to the list
                        if isinstance(self.descriptions[idx], list):
                            self.descriptions[idx].append(description)
                        else:
                            self.descriptions[idx] = [self.descriptions[idx], description]
                except TaskCanceledException:
                    raise
                except Exception as e:
                    logging.warning(f"[VisionFigureParser] figure={idx} processing failed: {e}")

        self._assemble()
        return self.assembled
