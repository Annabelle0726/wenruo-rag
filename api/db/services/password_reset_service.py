"""Bounded, single-use reset codes shared across API workers in Redis."""

import hashlib
import hmac
import secrets

from peewee import fn
from werkzeug.security import generate_password_hash

from api.db.db_models import DB, User
from api.db.services.invitation_service import normalize_email, password_value
from api.utils.web_utils import send_email_html
from common import settings
from common.misc_utils import get_uuid
from rag.utils.redis_conn import REDIS_CONN

TTL = 300
CONSUME = """
local value = redis.call('HGET', KEYS[1], 'digest')
if not value then return 0 end
local attempts = redis.call('HINCRBY', KEYS[1], 'attempts', 1)
if attempts > 5 then redis.call('DEL', KEYS[1]); return 0 end
if value ~= ARGV[1] then
  if attempts == 5 then redis.call('DEL', KEYS[1]) end
  return 0
end
redis.call('DEL', KEYS[1])
return 1
"""


def _key(email):
    return "password-reset:" + hashlib.sha256(email.encode()).hexdigest()


def _digest(email, code):
    return hmac.new(settings.get_secret_key().encode(), f"{email}:{code}".encode(), hashlib.sha256).hexdigest()


@DB.connection_context()
def _account(email):
    return User.get_or_none(fn.LOWER(User.email) == email, User.status == "1", User.is_active == "1", User.login_channel == "password")


async def send_code(email):
    email = normalize_email(email)
    if not settings.MAIL_SERVER or not settings.MAIL_PORT or len(settings.MAIL_DEFAULT_SENDER) != 2 or not settings.MAIL_DEFAULT_SENDER[1]:
        raise ValueError("Password recovery email is not configured. Contact your administrator.")
    redis = REDIS_CONN.REDIS
    key = _key(email)
    if not redis.set(key + ":cooldown", "1", ex=60, nx=True):
        raise ValueError("Please wait a minute before requesting another code.")
    # Same response for missing, disabled and external-login accounts.
    if not _account(email):
        return
    code = f"{secrets.randbelow(1_000_000):06d}"
    with redis.pipeline(transaction=True) as pipe:
        pipe.delete(key)
        pipe.hset(key, mapping={"digest": _digest(email, code), "attempts": 0})
        pipe.expire(key, TTL)
        pipe.execute()
    try:
        await send_email_html(to_email=email, subject="Password reset", template_key="reset_code", code=code, ttl_min=5)
    except Exception:
        redis.delete(key)
        raise ValueError("Unable to send recovery email. Contact your administrator.") from None


@DB.connection_context()
def reset_password(email, code, new_password):
    email = normalize_email(email)
    if not isinstance(code, str) or len(code) != 6 or not code.isascii() or not code.isdigit():
        raise PermissionError("Invalid or expired verification code.")
    encoded = password_value(new_password)
    if not REDIS_CONN.REDIS.eval(CONSUME, 1, _key(email), _digest(email, code)):
        raise PermissionError("Invalid or expired verification code.")
    # Rotating the access token invalidates every existing authenticated session.
    updated = (
        User.update(password=generate_password_hash(encoded), access_token=get_uuid())
        .where(
            fn.LOWER(User.email) == email,
            User.status == "1",
            User.is_active == "1",
            User.login_channel == "password",
        )
        .execute()
    )
    if not updated:
        raise PermissionError("Invalid or expired verification code.")
