"""Durable provider-health INCIDENTS: emit a failure, resolve it on success, read it.

Three rules shape this module.

**It counts incidents, not failures.** One provider capability failing repeatedly
collapses into ONE active row whose `occurrence_count` grows. That is what turns a
GeminiEmbed quota burst across three page batches into a single incident rather
than three notifications, and it is why `dedupe_key` is derived from the identity
of the problem - workspace, provider, capability, error class and HTTP status -
and never from the page, the batch or the message text.

**It is fail-open by construction.** `emit_failure` and `resolve_on_success` never
raise: a health fact is an observation ABOUT a failure, so a store problem must
not change the exception the caller is already propagating, must not become a new
blocking point on the parse or chat path, must make no external network call, and
must never poll a provider. Every entry point swallows its own error to the log.

**It stores nothing sensitive.** The caller passes the CLASSIFICATION
(`common.model_errors.classify` already produced it) and a safe sentence; the raw
provider body, the key, the prompt, the chunk text and the request payload are not
parameters of this API at all, so they cannot be persisted by accident.

**Call sites reach it through ``CapabilityObserver``, not by calling the writers
directly.** The observer is installed by the orchestration layer that already holds
a proven provider identity, and it enforces the two things a hot path needs: one
fact per task, and an explicit scalar-only hand-off into the store.
"""

import functools
import hashlib
import logging
from datetime import datetime, timezone as utc_timezone
from uuid import uuid4

from api.db.db_models import DB, ProviderHealthEvent
from common import model_errors

ACTIVE = "active"
RESOLVED = "resolved"

RESOLUTION_OBSERVED_SUCCESS = "observed_success"

#: The capability an incident is grouped by. Lowercase and identical to the
#: matching ``LLMType`` value, so a filter and a reader use the same word.
CAPABILITY_EMBEDDING = "embedding"

#: The two calls an embedding bundle exposes. Observed together because a provider
#: that refuses a batch and a provider that refuses a query are the same provider
#: failing the same capability.
EMBEDDING_CALL_METHODS = ("encode", "encode_queries")

#: How serious a class is. A spent quota or a rejected credential needs a person;
#: a pacing limit or a timeout usually clears itself.
SEVERITY_BY_ERROR_CLASS = {
    model_errors.EMBEDDING_QUOTA_EXHAUSTED: "error",
    model_errors.EMBEDDING_RATE_LIMITED: "warning",
}

#: Fallback sentence when the caller has no classified message. It says what is
#: known - the provider refused - and nothing about a cause it cannot prove.
GENERIC_MESSAGE = "AI 服务调用失败，请稍后重试；若持续失败请联系管理员。"

#: A provider capability that never recovers would otherwise pin an incident open
#: forever. A new failure reopens the incident after this long without a repeat.
ACTIVE_WINDOW_SECONDS = 24 * 60 * 60


def dedupe_key(tenant_id, provider_id, instance_id, capability, error_class, http_status):
    """The identity of a health PROBLEM, as one opaque string.

    Deliberately excludes the timestamp, the page range, the batch index and the
    message text: including any of them would make every occurrence its own
    incident, which is the behaviour this exists to prevent.

    It deliberately INCLUDES the provider instance. Two instances of one provider
    are two endpoints with their own credentials, so a spent quota on one says
    nothing about the other - and, more to the point, one of them answering proves
    nothing about the other. Keying on the instance is what makes a recovery
    attributable: without it the first refusal of either instance owns the shared
    row, and a healthy instance could close an incident it never raised.
    """
    parts = "|".join(
        str(part if part is not None else "") for part in (tenant_id, provider_id, instance_id, capability, error_class, http_status)
    )
    return hashlib.sha256(parts.encode()).hexdigest()


def severity_of(error_class):
    return SEVERITY_BY_ERROR_CLASS.get(error_class, "error")


def safe_message_of(error_class):
    return model_errors.MESSAGES.get(error_class) or GENERIC_MESSAGE


def _now(now=None):
    return now or datetime.now(utc_timezone.utc).replace(tzinfo=None)


def emit_failure(
    tenant_id,
    provider_name,
    capability,
    error_class,
    *,
    provider_id="",
    instance_id="",
    http_status=None,
    affected_operation="",
    user_safe_message=None,
    now=None,
):
    """Record one occurrence; returns the incident id, or None if it could not.

    Never raises. A failure here is logged and swallowed, because the caller is
    already handling a provider exception and this write must not replace it,
    delay it or change its type.
    """
    if not tenant_id or not capability or not error_class:
        return None

    moment = _now(now)
    key = dedupe_key(tenant_id, provider_id, instance_id, capability, error_class, http_status)
    try:
        with DB.connection_context(), DB.atomic():
            incident = ProviderHealthEvent.get_or_none(ProviderHealthEvent.dedupe_key == key)
            if incident is not None and incident.state == ACTIVE:
                # Same active problem: count the occurrence, move the clock, and
                # create nothing - no second incident and no second notification.
                ProviderHealthEvent.update(
                    occurrence_count=incident.occurrence_count + 1,
                    last_seen_at=moment,
                ).where(ProviderHealthEvent.id == incident.id).execute()
                return incident.id

            if incident is not None and (moment - incident.last_seen_at).total_seconds() < ACTIVE_WINDOW_SECONDS:
                # Resolved recently and the problem is back: refresh the same row
                # rather than starting a parallel history for one problem.
                ProviderHealthEvent.update(
                    state=ACTIVE,
                    occurrence_count=incident.occurrence_count + 1,
                    last_seen_at=moment,
                    resolved_at=None,
                    resolution_kind=None,
                    severity=severity_of(error_class),
                    user_safe_message=user_safe_message or safe_message_of(error_class),
                ).where(ProviderHealthEvent.id == incident.id).execute()
                return incident.id

            incident_id = uuid4().hex
            if incident is not None:
                # A stale row still owns the unique dedupe key; it keeps the history
                # of the old episode under a suffixed key so the new one can be
                # created without deleting anything.
                ProviderHealthEvent.update(dedupe_key=f"{key[:52]}-{incident_id[:11]}").where(
                    ProviderHealthEvent.id == incident.id
                ).execute()
            ProviderHealthEvent.create(
                id=incident_id,
                tenant_id=tenant_id,
                provider_id=provider_id or "",
                instance_id=instance_id or "",
                provider_name=provider_name or "",
                capability=capability,
                error_class=error_class,
                http_status=http_status,
                severity=severity_of(error_class),
                occurred_at=moment,
                last_seen_at=moment,
                occurrence_count=1,
                affected_operation=affected_operation or "",
                user_safe_message=user_safe_message or safe_message_of(error_class),
                dedupe_key=key,
                state=ACTIVE,
            )
            return incident_id
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract here
        logging.warning(
            "Provider health incident could not be recorded (%s/%s): %s",
            provider_name,
            capability,
            exc,
        )
        return None


def resolve_on_success(tenant_id, provider_id="", capability="", *, instance_id="", now=None):
    """Close the active incidents of one provider capability; never raises.

    Only a SUCCESSFUL dispatch calls this. Opening the notification bell is not
    evidence that a provider recovered, so reading a notification must never reach
    this function; an operator who wants to close an incident does it explicitly,
    with `resolution_kind="acknowledged"`.

    ``instance_id`` narrows the closure to one instance of the provider, because
    two configured instances are two endpoints with their own keys and one of them
    working says nothing about the other. A row carrying no instance (written by a
    call site that could not prove one) stays closable, so a weakly-attributed
    fact cannot pin an incident open forever.
    """
    if not tenant_id or not capability:
        return 0

    moment = _now(now)
    try:
        with DB.connection_context(), DB.atomic():
            query = ProviderHealthEvent.update(
                state=RESOLVED,
                resolved_at=moment,
                resolution_kind=RESOLUTION_OBSERVED_SUCCESS,
            ).where(
                (ProviderHealthEvent.tenant_id == tenant_id)
                & (ProviderHealthEvent.capability == capability)
                & (ProviderHealthEvent.state == ACTIVE)
            )
            if provider_id:
                query = query.where(ProviderHealthEvent.provider_id == provider_id)
            if instance_id:
                query = query.where((ProviderHealthEvent.instance_id == instance_id) | (ProviderHealthEvent.instance_id == ""))
            return query.execute()
    except Exception as exc:  # noqa: BLE001 - fail-open is the contract here
        logging.warning("Provider health incidents could not be resolved: %s", exc)
        return 0


class CapabilityObserver:
    """Watches ONE provider capability's calls and reports them to the store.

    An orchestration layer that already holds a PROVEN provider identity installs
    this on the model bundle it is about to use, so every call the task makes -
    the bind probe, every embedding batch, every late stage - is observed through
    one object with one identity, instead of each call site guessing who it is
    talking to.

    Three properties make it safe on a hot path:

    * **Fail-open.** It cannot change what it observes. A failure is re-raised
      untouched by a bare ``raise``, an unrecognised failure is recorded not at
      all, and the store swallows its own errors - so a parse that succeeded
      still succeeds, and a parse that failed still fails with the same exception
      type, message, ``error_type`` and ``retryable`` flag.
    * **At most one fact per task.** One parse issues hundreds of embedding
      calls. The first observable success resolves and the first RECOGNISED
      failure records; every later call of the same task is a plain pass-through.
      That is what keeps a burst of refusals as one incident rather than one per
      batch, and it keeps the store off the per-batch path.
    * **Scalars only.** The identity arrives as five explicit strings and the
      classification as one string. There is no parameter for a model config, a
      raw body, a key, a prompt or a chunk, so none of them can reach the store
      through this object.
    """

    def __init__(self, *, tenant_id, provider_id, instance_id, provider_name, capability):
        self._tenant_id = tenant_id
        self._provider_id = provider_id
        self._instance_id = instance_id
        self._provider_name = provider_name
        self._capability = capability
        # One success and one failure per task, not per call.
        self._resolved = False
        self._recorded = False

    @classmethod
    def from_identity(cls, identity, capability):
        """Build an observer from a resolved identity, field by field.

        Each field is named on purpose: ``**identity`` (or forwarding the object
        itself) would let a future field of the identity type travel into the
        store the day it is added. Named scalars cannot.
        """
        return cls(
            tenant_id=identity.tenant_id,
            provider_id=identity.provider_id,
            instance_id=identity.instance_id,
            provider_name=identity.provider_name,
            capability=capability,
        )

    def wrap(self, call):
        """Return *call* with this observer around it, signature untouched.

        Returns a plain function, so it is still usable exactly where the original
        method was - including handed to a thread pool as a bare callable - and it
        carries the original's name, docstring and signature, so nothing that
        introspects the bundle can tell that it is being observed.
        """

        @functools.wraps(call)
        def observed(*args, **kwargs):
            try:
                result = call(*args, **kwargs)
            except Exception as exc:
                # ``finally: raise`` makes the invariant local rather than a
                # consequence of how ``failure`` happens to be written today: the
                # provider's own exception is what the caller sees, whatever the
                # observer did or failed to do.
                try:
                    self.failure(exc)
                finally:
                    raise
            self.success()
            return result

        return observed

    def success(self):
        """The capability answered; close its incidents once per task.

        A store problem here must not turn a WORKING call into a failed one, so
        this never raises.
        """
        if self._resolved:
            return
        self._resolved = True
        try:
            resolve_on_success(
                self._tenant_id,
                self._provider_id,
                self._capability,
                instance_id=self._instance_id,
            )
        except Exception as exc:  # noqa: BLE001 - fail-open is the contract here
            logging.warning("Provider recovery could not be recorded: %s", exc)

    def failure(self, exc):
        """Record one recognised provider failure, once per task.

        The class comes from the exception's own typed field first, then from the
        shared classifier reading its text - the same precedence the client-facing
        error path uses, so a fact and the message a user saw never disagree. The
        text is only ever READ here; it is not a parameter of the store.

        Never raises, for the same reason ``emit_failure`` never raises.
        """
        if self._recorded:
            return

        error_class = getattr(exc, "error_type", None) or model_errors.classify(str(exc))
        if not error_class:
            # An unrecognised failure is a bug, not a provider health fact.
            return

        self._recorded = True
        try:
            emit_failure(
                self._tenant_id,
                self._provider_name,
                self._capability,
                error_class,
                provider_id=self._provider_id,
                instance_id=self._instance_id,
            )
        except Exception as store_exc:  # noqa: BLE001 - fail-open is the contract here
            logging.warning("Provider failure could not be recorded: %s", store_exc)


def observe_calls(target, identity, *, capability, methods):
    """Shadow *methods* on *target* with a ``CapabilityObserver``.

    Returns the observer, or ``None`` when nothing could be installed - an
    identity that does not resolve, a target without those methods, or an object
    that refuses the assignment. Every one of those is a missing observation, not
    a broken call: the caller keeps working on the unobserved path.

    The methods are shadowed on the INSTANCE rather than the object being wrapped,
    so every other use of it is untouched: ``isinstance``, attribute access and the
    context-manager protocol all still see the original bundle. Wrapping the object
    would have changed how it is used, which is not something a side-channel may do.
    """
    if target is None or not methods:
        return None

    try:
        observer = CapabilityObserver.from_identity(identity, capability)
    except Exception as exc:  # noqa: BLE001 - a side-channel never blocks the path
        logging.warning("Provider call observation could not be prepared: %s", exc)
        return None

    installed = False
    for name in methods:
        call = getattr(target, name, None)
        if not callable(call):
            continue
        try:
            setattr(target, name, observer.wrap(call))
        except Exception as exc:  # noqa: BLE001
            logging.warning("Provider call observation could not be installed on %s: %s", name, exc)
            continue
        installed = True

    return observer if installed else None


def list_incidents(tenant_id, *, include_resolved=True, limit=50):
    """Active incidents first, then the most recently resolved ones.

    The projection is exactly what the console may show. There is no balance, no
    remaining quota, no latency and no raw body - none of those is stored, so none
    can leak through this read.
    """
    if not tenant_id:
        return []

    query = ProviderHealthEvent.select().where(ProviderHealthEvent.tenant_id == tenant_id)
    if not include_resolved:
        query = query.where(ProviderHealthEvent.state == ACTIVE)

    rows = list(
        query.order_by(
            ProviderHealthEvent.state.asc(),
            ProviderHealthEvent.last_seen_at.desc(),
        ).limit(max(1, min(int(limit or 50), 200)))
    )
    return [
        {
            "id": row.id,
            "provider_name": row.provider_name,
            "capability": row.capability,
            "error_class": row.error_class,
            "http_status": row.http_status,
            "severity": row.severity,
            "occurred_at": row.occurred_at.strftime("%Y-%m-%d %H:%M:%S") if row.occurred_at else None,
            "last_seen_at": row.last_seen_at.strftime("%Y-%m-%d %H:%M:%S") if row.last_seen_at else None,
            "occurrence_count": row.occurrence_count,
            "affected_operation": row.affected_operation,
            "user_safe_message": row.user_safe_message,
            "state": row.state,
            "resolved_at": row.resolved_at.strftime("%Y-%m-%d %H:%M:%S") if row.resolved_at else None,
            "resolution_kind": row.resolution_kind,
        }
        for row in rows
    ]


def active_incident_count(tenant_id):
    """How many incidents the notification badge should count. Never raises."""
    if not tenant_id:
        return 0
    try:
        with DB.connection_context():
            return (
                ProviderHealthEvent.select()
                .where((ProviderHealthEvent.tenant_id == tenant_id) & (ProviderHealthEvent.state == ACTIVE))
                .count()
            )
    except Exception as exc:  # noqa: BLE001
        logging.warning("Provider health incident count unavailable: %s", exc)
        return 0
