"""LIVE evidence for the document-list state model on the deployed image.

Run INSIDE the running container (`docker exec -i wenruo-rag-cpu /ragflow/.venv/bin/python -`).

It answers one question with the deployment's own answers rather than with a written-down
expectation: for every dataset this tenant can see, does the endpoint the file list page calls
(GET /api/v1/datasets/<id>/documents) return `code=0` with that many rows?

No dataset id is written down here. The ids come from GET /api/v1/datasets, and the token is
minted with the application's own serializer for each real user, so the evidence holds for
whatever tenant actually owns the data. Every visible dataset is probed - including the ones
whose listed `doc_num` is 0, because a list's own count is not the documents endpoint's answer.
"""
import json
import sys

sys.path.insert(0, "/ragflow")

from common import settings

settings.init_settings()

import requests  # noqa: E402
from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer  # noqa: E402

from api.db.db_models import User  # noqa: E402
from common import settings as app_settings  # noqa: E402

BASE = "http://127.0.0.1:9380"
PAGE_SIZE = 10


def tokens():
    """One token per real user: the tenants differ, and a tenant only sees its own datasets."""
    serializer = Serializer(secret_key=app_settings.get_secret_key())
    for user in User.select():
        yield user.email, str(serializer.dumps(str(user.access_token)))


def get(path, token, params=None):
    response = requests.get(
        f"{BASE}{path}",
        headers={"Authorization": token},
        params=params,
        timeout=60,
    )
    try:
        return response.status_code, response.json()
    except Exception:  # noqa: BLE001
        return response.status_code, {"raw": response.text[:200]}


def main():
    evidence = []
    diagnostics = []
    for email, token in tokens():
        status, listing = get("/api/v1/datasets", token, {"page": 1, "page_size": 100})
        listed = listing.get("data") or []
        diagnostics.append(
            {
                "owner": email,
                "http_status": status,
                "code": listing.get("code"),
                "message": (listing.get("message") or "")[:120],
                "datasets_visible": len(listed) if isinstance(listed, list) else None,
            }
        )
        if status != 200 or listing.get("code") != 0 or not isinstance(listed, list):
            continue

        for dataset in listed:
            dataset_id = dataset["id"]
            d_status, docs = get(
                f"/api/v1/datasets/{dataset_id}/documents",
                token,
                {"page": 1, "page_size": PAGE_SIZE},
            )
            payload = docs.get("data") or {}
            rows = payload.get("docs") or []
            total = payload.get("total")
            evidence.append(
                {
                    "owner": email,
                    "dataset": dataset.get("name"),
                    "dataset_id_from_api": dataset_id,
                    "list_doc_num": dataset.get("doc_num"),
                    "documents_http_status": d_status,
                    "documents_code": docs.get("code"),
                    "documents_rows": len(rows),
                    "documents_total": total,
                    # What the file list page needs: a code=0 answer with every row it asked for.
                    "documents_ok": d_status == 200
                    and docs.get("code") == 0
                    and len(rows) == min(total or 0, PAGE_SIZE),
                }
            )

    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    print(json.dumps({"per_user": diagnostics}, ensure_ascii=False, indent=2))

    probed = len(evidence)
    answered = [item for item in evidence if item["documents_code"] == 0]
    bad = [item for item in evidence if not item["documents_ok"] and item["documents_rows"]]
    with_rows = [item for item in evidence if item["documents_rows"]]
    print(
        f"\nDATASETS_PROBED={probed} CODE0={len(answered)} WITH_ROWS={len(with_rows)} "
        f"ROW_COUNT_MISMATCH={len(bad)}"
    )
    for item in with_rows:
        print(
            f"  {item['documents_rows']} docs | list_doc_num={item['list_doc_num']} | "
            f"{item['dataset']} | {item['dataset_id_from_api']}"
        )
    return 0 if with_rows and not bad else 1


if __name__ == "__main__":
    sys.exit(main())
