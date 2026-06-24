"""Azure CLI / ARM REST API helpers for PIM role management.

All I/O goes through `az rest` so that authentication is delegated to
the Azure CLI session already active in the terminal.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run_az(*args: str) -> Any:
    """Run an `az` CLI command and return parsed JSON output.

    Raises RuntimeError on non-zero exit or if `az` is not found.
    """
    log.debug("az %s", " ".join(args))
    try:
        result = subprocess.run(
            ["az", *args, "--output", "json"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        raise RuntimeError(
            "Azure CLI not found. Install it: https://aka.ms/installazurecli"
        )
    if result.returncode != 0:
        msg = result.stderr.strip()
        log.error(
            "az %s failed (exit %d):\n%s",
            " ".join(args),
            result.returncode,
            msg,
        )
        raise RuntimeError(msg or f"az {' '.join(args)} exited {result.returncode}")
    log.debug("az response: %s", result.stdout[:2000])
    return json.loads(result.stdout)


def is_auth_error(msg: str) -> bool:
    """Return True if *msg* indicates an expired or missing Azure CLI session."""
    lowered = msg.lower()
    return any(
        token in lowered
        for token in (
            "refresh token",
            "aadsts",
            "az login",
            "not logged in",
            "please run",
            "unauthorized",
        )
    )


def is_scope_error(msg: str) -> bool:
    """Return True if *msg* indicates a missing OAuth scope / consent."""
    lowered = msg.lower()
    return any(
        token in lowered
        for token in (
            "permissionscopenotgranted",
            "authorization_requestdenied",
            "insufficient privileges",
        )
    )


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class Subscription:
    id: str
    name: str


@dataclass
class EligibleRole:
    role_name: str
    role_definition_id: str
    scope: str               # actual assignment scope: /subscriptions/{id} or /providers/Microsoft.Management/managementGroups/{id}
    scope_display_name: str  # human-readable scope name
    principal_id: str
    eligibility_schedule_id: str  # short GUID used in linkedRoleEligibilityScheduleId
    expiry: str | None            # ISO 8601 datetime string or None
    is_active: bool = False       # True if already PIM-activated

    @property
    def is_global(self) -> bool:
        """True if assigned at management group or root scope (not subscription-scoped)."""
        return not self.scope.startswith("/subscriptions/")


@dataclass
class EntraEligibleRole:
    role_name: str
    role_definition_id: str
    principal_id: str
    eligibility_schedule_id: str  # unifiedRoleEligibilitySchedule id
    expiry: str | None
    is_active: bool = False


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

_DURATION_RE = re.compile(
    r"^P(?:\d+Y)?(?:\d+M)?(?:\d+D)?(?:T(?:\d+H)?(?:\d+M)?(?:\d+(?:\.\d+)?S)?)?$"
)


def validate_duration(s: str) -> bool:
    """Return True if *s* is a non-trivial ISO 8601 duration (e.g. PT8H)."""
    return bool(_DURATION_RE.match(s)) and s not in ("P", "PT")


def format_expiry(expiry: str | None) -> str:
    """Shorten an ISO 8601 datetime to YYYY-MM-DD, or return '—'."""
    if not expiry:
        return "—"
    return expiry[:10]


# ---------------------------------------------------------------------------
# Azure API calls
# ---------------------------------------------------------------------------

def get_current_user() -> str:
    """Return the object ID of the currently signed-in user."""
    data = _run_az("ad", "signed-in-user", "show")
    return data["id"]


def list_subscriptions() -> list[Subscription]:
    """Return all subscriptions visible to the current account."""
    data = _run_az("account", "list")
    return [Subscription(id=s["id"], name=s["name"]) for s in data]


def _list_active_role_keys(scope: str) -> frozenset[tuple[str, str]]:
    """Return a set of (role_definition_id, scope) for currently active PIM assignments."""
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleAssignmentScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    try:
        data = _run_az("rest", "--method", "GET", "--url", url)
    except RuntimeError:
        return frozenset()
    keys: set[tuple[str, str]] = set()
    for item in data.get("value", []):
        props = item.get("properties", {})
        # Only count Activated (PIM-activated) assignments, not permanent ones
        if props.get("assignmentType") != "Activated":
            continue
        expanded = props.get("expandedProperties", {})
        role_def_id = props.get("roleDefinitionId", "")
        active_scope = expanded.get("scope", {}).get("id") or scope
        keys.add((role_def_id, active_scope))
    return frozenset(keys)


def list_eligible_roles(subscription_id: str) -> list[EligibleRole]:
    """List eligible PIM role assignments for the signed-in user in *subscription_id*.

    Roles that are already active (PIM-activated) are excluded from the result.
    """
    scope = f"/subscriptions/{subscription_id}"
    url = (
        f"https://management.azure.com{scope}"
        f"/providers/Microsoft.Authorization/roleEligibilityScheduleInstances"
        f"?$filter=asTarget()&api-version=2020-10-01"
    )
    # Resolve the signed-in user's own object ID once.
    # When a role eligibility is assigned to a group, the API returns the
    # group's principalId — but SelfActivate requires the requesting *user's*
    # object ID.  We always substitute the real user ID here so activation
    # works for both direct and group-based eligibilities.
    user_id = get_current_user()
    active_keys = _list_active_role_keys(scope)
    data = _run_az("rest", "--method", "GET", "--url", url)
    roles: list[EligibleRole] = []
    for item in data.get("value", []):
        props = item.get("properties", {})
        expanded = props.get("expandedProperties", {})
        # Extract the short GUID from the full resource path
        sched_path: str = props.get("roleEligibilityScheduleId", "")
        sched_id = sched_path.rsplit("/", 1)[-1] if "/" in sched_path else item.get("name", str(uuid.uuid4()))
        actual_scope = expanded.get("scope", {}).get("id") or scope
        role_def_id = props.get("roleDefinitionId", "")
        already_active = (role_def_id, actual_scope) in active_keys
        if already_active:
            log.debug("marking already-active role %s on %s", role_def_id, actual_scope)
        roles.append(
            EligibleRole(
                role_name=expanded.get("roleDefinition", {}).get("displayName", "Unknown"),
                role_definition_id=role_def_id,
                scope=actual_scope,
                scope_display_name=(
                    expanded.get("scope", {}).get("displayName") or subscription_id
                ),
                principal_id=user_id,
                eligibility_schedule_id=sched_id,
                expiry=props.get("endDateTime"),
                is_active=already_active,
            )
        )
    return roles


def activate_role(
    role: EligibleRole,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> dict:
    """Submit a SelfActivate request for an eligible PIM role.

    Returns the ARM response dict.  When *dry_run* is True the API call
    is skipped and a synthetic response is returned instead.
    """
    request_id = str(uuid.uuid4())
    if dry_run:
        log.debug("dry-run: skipping activation of %s", role.role_name)
        return {
            "name": request_id,
            "properties": {"status": "DryRun", "requestType": "SelfActivate"},
        }
    body = json.dumps(
        {
            "properties": {
                "principalId": role.principal_id,
                "roleDefinitionId": role.role_definition_id,
                "requestType": "SelfActivate",
                "linkedRoleEligibilityScheduleId": role.eligibility_schedule_id,
                "scheduleInfo": {
                    "expiration": {
                        "type": "AfterDuration",
                        "duration": duration,
                    }
                },
                "justification": justification,
            }
        }
    )
    url = (
        f"https://management.azure.com{role.scope}"
        f"/providers/Microsoft.Authorization"
        f"/roleAssignmentScheduleRequests/{request_id}?api-version=2020-10-01"
    )
    log.debug(
        "activating role %s on %s (request %s)", role.role_name, role.scope, request_id
    )
    response = _run_az(
        "rest", "--method", "PUT", "--url", url, "--body", body,
        "--headers", "Content-Type=application/json",
    )
    log.debug(
        "activation response for %s: status=%s",
        role.role_name,
        response.get("properties", {}).get("status"),
    )
    return response


# ---------------------------------------------------------------------------
# Microsoft Entra (Azure AD) PIM — Graph API
# ---------------------------------------------------------------------------

_GRAPH = "https://graph.microsoft.com"


def _list_active_entra_role_def_ids(principal_id: str) -> frozenset[str]:
    """Return role definition IDs currently PIM-activated in Entra for *principal_id*."""
    url = (
        f"{_GRAPH}/v1.0/roleManagement/directory/roleAssignmentScheduleInstances"
        f"?$filter=principalId eq '{principal_id}' and assignmentType eq 'Activated'"
    )
    try:
        data = _run_az("rest", "--method", "GET", "--url", url, "--resource", _GRAPH)
    except RuntimeError:
        return frozenset()
    return frozenset(item.get("roleDefinitionId", "") for item in data.get("value", []))


def list_entra_eligible_roles() -> list[EntraEligibleRole]:
    """List eligible Entra PIM role assignments for the signed-in user."""
    user_id = get_current_user()
    active_def_ids = _list_active_entra_role_def_ids(user_id)
    url = (
        f"{_GRAPH}/v1.0/roleManagement/directory/roleEligibilityScheduleInstances"
        f"?$filter=principalId eq '{user_id}'&$expand=roleDefinition"
    )
    data = _run_az("rest", "--method", "GET", "--url", url, "--resource", _GRAPH)
    roles: list[EntraEligibleRole] = []
    for item in data.get("value", []):
        role_def = item.get("roleDefinition") or {}
        role_def_id = item.get("roleDefinitionId", "")
        roles.append(
            EntraEligibleRole(
                role_name=role_def.get("displayName", "Unknown"),
                role_definition_id=role_def_id,
                principal_id=user_id,
                eligibility_schedule_id=item.get(
                    "roleEligibilityScheduleId", item.get("id", str(uuid.uuid4()))
                ),
                expiry=item.get("endDateTime"),
                is_active=role_def_id in active_def_ids,
            )
        )
    return roles


def activate_entra_role(
    role: EntraEligibleRole,
    justification: str,
    duration: str,
    dry_run: bool = False,
) -> dict:
    """Submit a selfActivate request for an Entra PIM role via Microsoft Graph."""
    request_id = str(uuid.uuid4())
    if dry_run:
        log.debug("dry-run: skipping Entra activation of %s", role.role_name)
        return {"id": request_id, "status": "DryRun"}
    body = json.dumps(
        {
            "action": "selfActivate",
            "principalId": role.principal_id,
            "roleDefinitionId": role.role_definition_id,
            "directoryScopeId": "/",
            "justification": justification,
            "scheduleInfo": {
                "expiration": {
                    "type": "afterDuration",
                    "duration": duration,
                }
            },
        }
    )
    url = f"{_GRAPH}/v1.0/roleManagement/directory/roleAssignmentScheduleRequests"
    log.debug("activating Entra role %s (request %s)", role.role_name, request_id)
    response = _run_az(
        "rest", "--method", "POST", "--url", url, "--body", body,
        "--headers", "Content-Type=application/json",
        "--resource", _GRAPH,
    )
    log.debug(
        "Entra activation response for %s: status=%s",
        role.role_name,
        response.get("status"),
    )
    return response

