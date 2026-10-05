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
"""Cable-domain scoping of the built-in agent templates.

The cable fork keeps every upstream template under ``agent/templates/`` byte for
byte and ships its own under ``agent/templates/cable_templates/``. Turning on
``show_cable_only`` (``conf/service_conf.yaml``) or ``SHOW_CABLE_ONLY`` (env)
narrows both canvas-template seeding and ``GET /agents/templates`` to the cable
directory, so the official templates stay on disk for future upstream merges
while the product only ever shows cable agents.
"""

import json
import logging
import os

from common.config_utils import get_base_config
from common.file_utils import get_project_base_directory

CABLE_ONLY_CONFIG_KEY = "show_cable_only"
CABLE_TEMPLATE_DIRNAME = "cable_templates"

_AGENT_DIRNAME = "agent"
_TEMPLATE_DIRNAME = "templates"
_TRUTHY_VALUES = frozenset({"1", "true", "yes", "on"})


def agent_templates_directory() -> str:
    return os.path.join(get_project_base_directory(), _AGENT_DIRNAME, _TEMPLATE_DIRNAME)


def cable_templates_directory() -> str:
    return os.path.join(agent_templates_directory(), CABLE_TEMPLATE_DIRNAME)


def _flag_enabled(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in _TRUTHY_VALUES
    if isinstance(value, (int, float)):
        return value != 0
    return False


def cable_only_enabled() -> bool:
    """Whether the cable domain replaces the official template catalogue."""
    return _flag_enabled(get_base_config(CABLE_ONLY_CONFIG_KEY))


def template_scope_directories() -> list[str]:
    """Template directories to seed, narrowed to the cable domain when enabled."""
    if cable_only_enabled():
        return [cable_templates_directory()]
    return [agent_templates_directory()]


def cable_template_ids() -> frozenset[str]:
    """Ids of the cable templates on disk, as stored in ``canvas_template.id``."""
    directory = cable_templates_directory()
    if not os.path.isdir(directory):
        logging.warning("Missing cable agent templates: %s", directory)
        return frozenset()

    ids: set[str] = set()
    for name in sorted(os.listdir(directory)):
        if not name.endswith(".json"):
            logging.debug("Skipping non-json cable template file in %s: %s", directory, name)
            continue
        template_path = os.path.join(directory, name)
        try:
            with open(template_path, "r", encoding="utf-8") as f:
                template_id = json.load(f).get("id")
        except Exception as e:
            logging.exception("Read cable template error for %s: %s", template_path, e)
            continue
        if template_id is None:
            logging.warning("Cable template without id: %s", template_path)
            continue
        ids.add(str(template_id))
    return frozenset(ids)


def filter_scoped_templates(templates):
    """Drop official templates from a ``canvas_template`` row set when cable-only is on.

    Rows seeded before the switch was turned on stay in the table until the next
    start-up reseed; hiding them here keeps the response cable-only in the meantime.
    """
    if not cable_only_enabled():
        return list(templates)
    cable_ids = cable_template_ids()
    return [template for template in templates if str(template.id) in cable_ids]
