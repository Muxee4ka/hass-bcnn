"""Repairs flow for Center-SBK.

Surfaces actionable issues to the user via the HA Repairs panel:

* parse_error — the cabinet HTML changed shape, the integration can no
  longer scrape it. The fix flow points users to file a bug. The issue is
  deleted automatically once the next update succeeds.
"""

from __future__ import annotations

from homeassistant.components.repairs import ConfirmRepairFlow, RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN

ISSUE_PARSE_ERROR = "parse_error"
ISSUE_URL = "https://github.com/Muxee4ka/hass-bcnn/issues"


def raise_parse_error_issue(hass: HomeAssistant, account: str, detail: str) -> None:
    """Create (or refresh) the parse-error repair issue for this account."""
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"{ISSUE_PARSE_ERROR}_{account}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key=ISSUE_PARSE_ERROR,
        translation_placeholders={"account": account, "detail": detail},
        learn_more_url=ISSUE_URL,
    )


def clear_parse_error_issue(hass: HomeAssistant, account: str) -> None:
    ir.async_delete_issue(hass, DOMAIN, f"{ISSUE_PARSE_ERROR}_{account}")


async def async_create_fix_flow(
    hass: HomeAssistant, issue_id: str, data: dict | None
) -> RepairsFlow:
    """Return the fix flow for an issue. We only need a confirm step."""
    return ConfirmRepairFlow()
