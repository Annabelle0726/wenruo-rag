"""Exercise the real cookie helpers without booting every application blueprint."""

import ast
import hashlib
import hmac
import logging
from pathlib import Path
from types import SimpleNamespace


def test_cookie_session_is_bound_to_the_current_access_token():
    source = Path("api/apps/__init__.py").read_text(encoding="utf-8")
    names = {"login_user", "_load_user_from_session"}
    tree = ast.parse(source)
    tree.body = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    user = SimpleNamespace(id="member", is_active="1", access_token="a" * 32)
    namespace = {
        "hashlib": hashlib,
        "hmac": hmac,
        "logging": logging,
        "session": {},
        "get_uuid": lambda: "session-id",
        "g": SimpleNamespace(),
        "AUTH_JWT": "jwt",
        "StatusEnum": SimpleNamespace(VALID=SimpleNamespace(value="1")),
        "UserService": SimpleNamespace(query=lambda **kwargs: [user]),
    }
    exec(compile(tree, "api/apps/__init__.py", "exec"), namespace)
    assert namespace["login_user"](user)
    assert namespace["_load_user_from_session"]() is user
    user.access_token = "b" * 32  # Password reset rotates the database token.
    assert namespace["_load_user_from_session"]() is None
    namespace["login_user"](user)
    assert namespace["_load_user_from_session"]() is user
    namespace["session"].pop("_user_token_digest")
    assert namespace["_load_user_from_session"]() is None
