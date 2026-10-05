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
"""Cable-domain defaults for a newly created dataset, chat assistant, or search app.

This fork is a cable-industry vertical, so a dataset, chat assistant, or search
app created without explicit retrieval or prompt settings starts from the cable
values below instead of the generic RAGFlow ones. The persisted model defaults
(``api/db/db_models.py``) and the API create defaults
(``api/apps/restful_apis/chat_api.py``, ``api/apps/restful_apis/search_api.py``)
read this module, so a row lands on the same configuration whichever path
created it: the UI, the SDK, or a direct service call.

This is the single source of truth on the Python side; the Go backend mirrors
the same values in ``internal/service/cable_defaults.go`` and reads them from
``internal/service/chat.go`` and ``internal/service/dataset/crud.go``.
"""

from copy import deepcopy
from typing import Any

#: Minimum similarity a passage must reach to be retrieved by a new dataset or
#: chat assistant.
#:
#: Measured on the cable corpus: with the hybrid weights below, a query that
#: matches three documents scores 0.61-0.68 for the passages that carry the
#: answer and 0.53-0.55 for the ones that merely mention the same words, with an
#: empty band in between. 0.55 sits under that gap, so a loosely worded query
#: still returns its answer while the tail that used to pad the reference list is
#: dropped. The earlier 0.25 was low enough to hand back every passage of a
#: 31-chunk corpus, which is what made a result page read as noise.
SIMILARITY_THRESHOLD = 0.55
#: Weight of the vector leg of the hybrid score. The full-text (keyword) leg
#: takes the remainder, i.e. 0.50.
#:
#: An even split keeps a model code or a 型号 matched literally by the keyword
#: leg on equal footing with the semantic match on 技术要求 prose. The earlier
#: 0.30 leaned on the keyword leg, which scored every passage of a document
#: equally once one of its terms matched.
VECTOR_SIMILARITY_WEIGHT = 0.50
#: Passages handed to the reranker.
#:
#: A search page shows a handful of references, so reranking more than a few
#: dozen candidates buys nothing but latency. The floor is
#: ``page * page_size`` at retrieval time (see
#: ``Dealer.retrieval``), which caps how small this can go.
RERANK_CANDIDATES_COUNT = 30
#: Passages kept for the answer handed to the LLM.
#:
#: 6 was measured to truncate real answers on a standards corpus: a coal-industry
#: standard of 47 chunks had its own 表3 (第4芯截面选用表) at retrieval rank 7 and
#: its 外护层 naming clause at rank 10, so both were dropped before the model ever
#: saw them — the answer then reported the content as missing from the document.
#: 12 keeps a single-document standards corpus covered without the context cost
#: that comes with routinely handing the model two dozen passages.
TOP_N = 12

#: System prompt of a new chat assistant. ``{knowledge}`` is where the retrieved
#: passages are injected; the declared parameters below must match it.
SYSTEM_PROMPT = (
    "你是一位经验丰富且亲切的线缆技术专家顾问。\n"
    "\n"
    "【沟通风格】\n"
    "- 请使用自然、流畅、口语化的语言回答问题，语气生动亲切。\n"
    "- 避免像机器一样机械地罗列硬邦邦的规范条款，把复杂的工程标准用通俗易懂的专业语言表达出来。\n"
    "\n"
    "【回答与推理原则】\n"
    "1. 自然表达与拒答：如果知识库中完全没有包含回答问题所需的信息，请用自然的口吻告知用户暂未查到相关资料即可，无需使用僵硬固定的模板（如“未找到您想要的答案”）。\n"
    "2. 弹性与例外条款优先：在回答基于标准规范的逻辑判定或选型问题时，必须优先检查标准文本中是否存在“例外条款”、“供需双方协商确定”、“补充协议规定”或“特殊工况说明”等弹性规定。只要标准允许协商或存在例外，不得仅凭通用常识直接否定。\n"
    "3. 合理工程推理：允许基于知识库提取出的物理结构特征（如铠装类型、材质、截面等），结合线缆工程常识进行合理的适用性分析。\n"
    "4. 标准号归属判定：当知识库文档的正文或切片前缀（形如“[标准号: Q/GDW 73289.2-2026 | 文档: …… | 章节: ……]”）标注了标准号时，该文档就是该标准的正文——即使它的文件名是《……采购标准》《……专用技术规范》等采购类名称，也只是这份标准的归档命名方式。请直接依据其内容回答该标准的问题，不得据此断定“知识库中只有采购标准、没有这份标准编号”而拒答。\n"
    "5. 证据不足时严格拒答：\n"
    "   - 如果证据里没有出现用户提问的所有关键实体，必须回答“知识库中未包含 XXX 的信息”，禁止用训练知识补全。\n"
    "   - 如果用户要对比两个实体，而证据里只有一个，只回答有的那个，并明确说“另一个未在知识库中找到”。\n"
    "   - 禁止给出“接近但不完全一致”的数值。\n"
    "   - 禁止给出证据中没有的数字、温度、参数。如果用户问的数值不在证据里，直接说“知识库中未找到该数值”。\n"
    "6. 检索片段与原文的区分：如果检索到的片段里没有包含回答所需的信息，请明确说明“当前检索到的片段暂未包含 X，建议补充关键词或指定条款号/表号”，"
    "不要据此判断标准原文缺失、残缺或不完整——原文可能含有该内容，只是本轮未被检索到。\n"
    "\n"
    "以下是知识库：\n"
    "{knowledge}\n"
    "以上是知识库。"
)

#: Opening line of a new chat assistant.
PROLOGUE = "您好！我是您的线缆技术与选型专家助手，请发送您的文件或提问合规校验及工程选型评估"

#: Answer shown when retrieval returns nothing, instead of asking the model.
EMPTY_RESPONSE = "暂未在知识库中检索到相关线缆参数或规范条款。您可以提供更具体的型号规格或更新补充文档"

#: Metadata matching mode a new chat assistant starts in.
#:
#: ``auto`` answers a corpus that is mostly standards and datasheets: the question
#: usually NAMES the thing it asks about (a 型号, a 标准号, a 物资类别), the documents
#: carry that name as metadata, and matching on it narrows the search to the right
#: document before either retrieval leg is asked to find a passage about it.
#: ``disabled`` - what an assistant used to start with - left every candidate in
#: play, which is what let a working document out-number the standard it belongs to.
#:
#: This is a MATCHING rule, not a corpus filter: the automatic matcher derives its
#: conditions from the question with one LLM call, and when it derives none (or
#: none match) retrieval proceeds unrestricted, exactly as before. On a dataset
#: that carries no metadata it therefore changes nothing.
META_DATA_FILTER_METHOD = "auto"

#: Prompt parameters the system prompt above declares. ``knowledge`` is filled by
#: the retrieval step, ``date`` is optional and filled from the request.
PROMPT_PARAMETERS = [
    {"key": "knowledge", "optional": False},
    {"key": "date", "optional": True},
]


def prompt_config() -> dict[str, Any]:
    """A fresh cable prompt configuration for a new chat assistant.

    A function rather than a module-level dict: every caller needs its own copy
    so one row's edits can never leak into another's.
    """
    return {
        "system": SYSTEM_PROMPT,
        "prologue": PROLOGUE,
        "parameters": [dict(parameter) for parameter in PROMPT_PARAMETERS],
        "empty_response": EMPTY_RESPONSE,
    }


def meta_data_filter() -> dict[str, Any]:
    """A fresh metadata-matching configuration for a new chat assistant.

    A function for the same reason as :func:`prompt_config`: the dict is stored per
    row, so a shared literal would be one object behind many assistants.
    """
    return {"method": META_DATA_FILTER_METHOD}


def meta_data_filter_with_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    """A stored metadata configuration with the cable default underneath it.

    An ABSENT or EMPTY configuration means "never configured", which the platform
    answers with automatic matching - that is what makes a NEW assistant start with
    metadata matching on. A configuration that names a method - including
    ``disabled``, and including ``manual``/``semi_auto`` with their conditions - is
    the operator's own decision and is returned as it stands.

    The result is a deep copy: it is handed to a request that goes on to mutate it
    (the settings form rewrites conditions in place), and a shared nested list
    would write that edit back into the stored configuration.
    """
    if stored:
        return deepcopy(dict(stored))
    return meta_data_filter()


def search_config() -> dict[str, Any]:
    """A fresh cable search configuration for a new search app.

    A function for the same reason as :func:`prompt_config`: the dict is stored
    per row and mutated in place by the settings form.

    ``rerank_id`` stays empty because a model id is a tenant's own; the
    retrieval path resolves the tenant's default rerank model for it, so rerank
    runs by default on a tenant that has one configured and stays off, rather
    than failing, on a tenant that does not.
    """
    return {
        "kb_ids": [],
        "doc_ids": [],
        "similarity_threshold": SIMILARITY_THRESHOLD,
        "vector_similarity_weight": VECTOR_SIMILARITY_WEIGHT,
        "use_kg": False,
        # rerank settings
        "rerank_id": "",
        "rerank_candidates_count": RERANK_CANDIDATES_COUNT,
        "top_k": 1024,
        # chat settings
        "summary": False,
        "chat_id": "",  # id of chat model in tenant_model table
        "llm_setting": {
            "temperature": 0.1,
            "top_p": 0.3,
            "frequency_penalty": 0.7,
            "presence_penalty": 0.4,
            "temperature_enabled": True,
            "top_p_enabled": True,
            "frequency_penalty_enabled": True,
            "presence_penalty_enabled": True,
        },
        "chat_settingcross_languages": [],
        "highlight": False,
        "keyword": False,
        "web_search": False,
        "related_search": False,
        "query_mindmap": False,
    }


def search_config_with_defaults(stored: dict[str, Any] | None) -> dict[str, Any]:
    """A stored search config with the cable defaults filled in underneath it.

    The platform defaults apply to every parameter a search app never wrote — a
    config created by an older build, by the SDK, or by hand — while a parameter
    the operator did set is returned exactly as it was.
    """
    return {**search_config(), **(stored or {})}
