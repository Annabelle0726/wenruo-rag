"""Requirement 7: prove the four provenance field NAMES need no mapping change.

Runs against the ISOLATED harness index (never production): creates a throwaway index from
`conf/mapping.json`, writes one document carrying the four fields, and reads the resulting mapping back.
If the existing dynamic templates type and store them, no `put_mapping` is required for ES/OpenSearch.
"""
import json
import pathlib
import sys

import pytest
import requests

sys.path.insert(0, "/ragflow")

CONF = "/ragflow/conf/service_conf.yaml"
FIELDS = (
    "content_prefix_kind_kwd",
    "content_prefix_version_int",
    "content_prefix_chars_int",
    "content_prefix_hash_kwd",
)
INDEX = "metadata_contract_mapping_gate"


def es_client():
    import yaml

    with open(CONF, encoding="utf-8") as handle:
        conf = yaml.safe_load(handle)["es"]
    return str(conf["hosts"]).rstrip("/"), (conf.get("username"), conf.get("password"))


def test_an_isolated_index_types_and_stores_the_provenance_fields():
    host, auth = es_client()
    mapping = json.loads(pathlib.Path("/ragflow/conf/mapping.json").read_text(encoding="utf-8"))
    body = {"settings": mapping.get("settings", {}), "mappings": mapping.get("mappings", {})}

    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)
    created = requests.put(f"{host}/{INDEX}", auth=auth, timeout=60, json=body)
    assert created.status_code in (200, 201), created.text[:400]

    document = {
        "id": "gate-1",
        "kb_id": "kb-gate",
        "doc_id": "doc-gate",
        "content_with_weight": "[标准号: Q/GDW 73286.2-2026 | 文档: 规范]附录.pdf] 正文",
        "content_prefix_kind_kwd": "identity_legacy",
        "content_prefix_version_int": 1,
        "content_prefix_chars_int": 41,
        "content_prefix_hash_kwd": "0123456789abcdef",
    }
    written = requests.post(f"{host}/{INDEX}/_doc/gate-1?refresh=true", auth=auth, timeout=30, json=document)
    assert written.status_code in (200, 201), written.text[:400]

    properties = requests.get(f"{host}/{INDEX}/_mapping", auth=auth, timeout=30).json()
    fields = list(properties.values())[0]["mappings"]["properties"]

    assert fields["content_prefix_kind_kwd"]["type"] == "keyword", fields.get("content_prefix_kind_kwd")
    assert fields["content_prefix_hash_kwd"]["type"] == "keyword", fields.get("content_prefix_hash_kwd")
    assert fields["content_prefix_version_int"]["type"] == "integer", fields.get("content_prefix_version_int")
    assert fields["content_prefix_chars_int"]["type"] == "integer", fields.get("content_prefix_chars_int")
    for name in ("content_prefix_kind_kwd", "content_prefix_hash_kwd", "content_prefix_version_int", "content_prefix_chars_int"):
        assert fields[name].get("store") is True, (name, fields[name])

    # The content field keeps its own template: stored, never searched.
    assert fields["content_with_weight"]["type"] == "text"
    assert fields["content_with_weight"].get("index") is False

    stored = requests.get(f"{host}/{INDEX}/_doc/gate-1", auth=auth, timeout=30).json()["_source"]
    for name in FIELDS:
        assert stored[name] == document[name], name

    requests.delete(f"{host}/{INDEX}", auth=auth, timeout=30)


def test_no_production_mapping_or_index_is_touched_by_this_gate():
    host, auth = es_client()
    assert "repair-es" in host or "127.0.0.1" in host, host
    indices = requests.get(f"{host}/_cat/indices?format=json", auth=auth, timeout=30).json()
    names = [row.get("index") for row in indices]
    assert INDEX not in names, "the throwaway index is removed again"
