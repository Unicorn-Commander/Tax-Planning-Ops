from __future__ import annotations

import hashlib
import logging
import time
from uuid import UUID

import httpx

from app.core.config import Settings

logger = logging.getLogger("tax_planning_ops.entitlement")

# --- Ops-Center tax_ops_access (the door) -----------------------------------
# Ops-Center owns plan entitlements. It answers
#   GET {OPS_CENTER_URL}/api/v1/entitlements?feature_key=tax_ops_access
# for the caller's OWN Keycloak bearer with
#   {"org_id", "org_name", "display_name", "slug", "tier", "role",
#    "entitlements": [...], "authorized": bool}
# Allowed ONLY on 200 with authorized is True AND an org bound to the
# workspace being entered: when the caller asks for ``org_id`` (the workspace's
# trusted org, resolved server-side) the answer's org_id must equal it exactly;
# with no org to ask for (a self-serve caller whose own workspace is not bound
# yet) the answer must name a canonical org uuid, which the caller is then
# bound to. Anything else (401/403/404/5xx, timeout, connection error,
# malformed JSON, missing or non-bool "authorized", a missing or different
# org_id) is a refusal: fail closed. Only a positive answer is cached, per
# (sub, requested org, bearer digest), for at most _TAX_OPS_CACHE_TTL_SECONDS:
# an answer for org A never serves org B, and a new bearer (a new session) is
# asked again. A refusal is never cached. The bearer itself is never stored.
TAX_OPS_FEATURE_KEY = "tax_ops_access"
_TAX_OPS_TIMEOUT_SECONDS = 3.0
_TAX_OPS_CACHE_TTL_SECONDS = 60.0
# (sub, requested org or "", sha256(bearer)) -> (allowed at, the org answered for)
_tax_ops_allowed: dict[tuple[str, str, str], tuple[float, str]] = {}


def clear_entitlement_cache() -> None:
    _tax_ops_allowed.clear()


def _refuse(reason: str) -> None:
    # One line per refused request, the status/reason only: never the token,
    # never the response body.
    logger.warning("tax_ops_access refused: %s", reason)


def _canonical_org(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        canonical = str(UUID(value))
    except ValueError:
        return None
    return canonical if canonical == value else None


async def tax_ops_org(
    *,
    bearer: str,
    sub: str,
    settings: Settings,
    org_id: str | None = None,
) -> str | None:
    """The Ops-Center org that entitles this caller to Tax-Planning-Ops, or None.

    ``bearer`` is the caller's own Keycloak access token. ``org_id`` is the
    TRUSTED org of the workspace being entered (never taken from the request);
    it is forwarded as ``?org_id=`` and the answer must be for exactly that org.
    Without it, the org Ops-Center resolves for the caller is returned. Callers
    must check ``ENTITLEMENT_CHECK_ENABLED`` themselves: this always asks."""
    base = settings.OPS_CENTER_URL.strip().rstrip("/")
    if not base:
        _refuse("OPS_CENTER_URL is not set")
        return None
    if not bearer or not sub:
        _refuse("no user bearer to present")
        return None
    key = (sub, org_id or "", hashlib.sha256(bearer.encode()).hexdigest())
    now = time.monotonic()
    cached = _tax_ops_allowed.get(key)
    if cached is not None and now - cached[0] < _TAX_OPS_CACHE_TTL_SECONDS:
        return cached[1]
    _tax_ops_allowed.pop(key, None)
    params = {"feature_key": TAX_OPS_FEATURE_KEY}
    if org_id:
        params["org_id"] = org_id
    try:
        async with httpx.AsyncClient(timeout=_TAX_OPS_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}/api/v1/entitlements",
                params=params,
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except httpx.TimeoutException:
        _refuse("timeout")
        return None
    except httpx.HTTPError as exc:
        _refuse(f"connection error ({type(exc).__name__})")
        return None
    if response.status_code != 200:
        _refuse(f"status {response.status_code}")
        return None
    try:
        body = response.json()
    except ValueError:
        _refuse("status 200, malformed JSON")
        return None
    if not isinstance(body, dict) or not isinstance(body.get("authorized"), bool):
        _refuse("status 200, no boolean 'authorized'")
        return None
    if body["authorized"] is not True:
        _refuse("status 200, authorized false")
        return None
    answered = _canonical_org(body.get("org_id"))
    if answered is None:
        _refuse("status 200, no org_id")
        return None
    if org_id and answered != org_id:
        _refuse("status 200, org_id is not the workspace's org")
        return None
    _tax_ops_allowed[key] = (now, answered)
    return answered


# --- Ops-Center org membership (the backfill's read) -------------------------
# The workspace-org backfill (task 33982835) asks, for a workspace's owner,
# which Ops-Center orgs they are owner or admin of, for the same feature:
#   GET {OPS_CENTER_URL}/api/v1/orgs?feature_key=tax_ops_access&uc_uid=<owner>
# with the OPERATOR's bearer (Ops-Center decides who may ask about others).
# Same trust model as the door: read-only GET, the caller's bearer forwarded,
# allowed ONLY on 200 with {"orgs": [{"org_id": <canonical uuid>, "role": str},
# ...]}; anything else (non-200, timeout, connection error, malformed JSON,
# missing/non-list "orgs", a non-canonical org_id, a missing role) is None —
# fail closed, the backfill then leaves the workspace unbound. Roles other
# than owner/admin are filtered out; duplicate org_ids collapse. Nothing is
# cached (a backfill run asks once; a stale answer during a bind run is worse)
# and the bearer is never stored or logged.
_OWNER_ADMIN_ROLES = frozenset({"owner", "admin"})


async def owner_admin_orgs(
    *,
    bearer: str,
    uc_uid: str,
    settings: Settings,
) -> list[str] | None:
    """The canonical org uuids where ``uc_uid`` is owner or admin, or None.

    None means "no answer to trust" (refused, unreachable, malformed): the
    caller must treat it as unknown, never as empty. The orgs come only from
    Ops-Center's answer — never from a request or argument value."""
    base = settings.OPS_CENTER_URL.strip().rstrip("/")
    if not base:
        _refuse("OPS_CENTER_URL is not set")
        return None
    if not bearer or not uc_uid:
        _refuse("no operator bearer or owner to ask about")
        return None
    try:
        async with httpx.AsyncClient(timeout=_TAX_OPS_TIMEOUT_SECONDS) as client:
            response = await client.get(
                f"{base}/api/v1/orgs",
                params={"feature_key": TAX_OPS_FEATURE_KEY, "uc_uid": uc_uid},
                headers={"Authorization": f"Bearer {bearer}"},
            )
    except httpx.TimeoutException:
        _refuse("orgs: timeout")
        return None
    except httpx.HTTPError as exc:
        _refuse(f"orgs: connection error ({type(exc).__name__})")
        return None
    if response.status_code != 200:
        _refuse(f"orgs: status {response.status_code}")
        return None
    try:
        body = response.json()
    except ValueError:
        _refuse("orgs: status 200, malformed JSON")
        return None
    if not isinstance(body, dict) or not isinstance(body.get("orgs"), list):
        _refuse("orgs: status 200, no 'orgs' list")
        return None
    orgs: list[str] = []
    for entry in body["orgs"]:
        if not isinstance(entry, dict) or not isinstance(entry.get("role"), str):
            _refuse("orgs: status 200, entry without a role")
            return None
        answered = _canonical_org(entry.get("org_id"))
        if answered is None:
            _refuse("orgs: status 200, entry without a canonical org_id")
            return None
        if entry["role"] in _OWNER_ADMIN_ROLES and answered not in orgs:
            orgs.append(answered)
    return orgs


async def check_tax_ops_access(
    *,
    bearer: str,
    sub: str,
    settings: Settings,
    org_id: str | None = None,
) -> bool:
    """Is the caller entitled to Tax-Planning-Ops (in ``org_id``, if given)?
    Off (ENTITLEMENT_CHECK_ENABLED=false) = allowed without asking."""
    if not settings.ENTITLEMENT_CHECK_ENABLED:
        return True
    return (
        await tax_ops_org(bearer=bearer, sub=sub, settings=settings, org_id=org_id)
        is not None
    )


def log_entitlement_config(settings: Settings) -> None:
    """One startup error line when the check is on but has nowhere to ask."""
    if settings.ENTITLEMENT_CHECK_ENABLED and not settings.OPS_CENTER_URL.strip():
        logger.error(
            "ENTITLEMENT_CHECK_ENABLED=true but OPS_CENTER_URL is empty: "
            "every caller will be refused"
        )
