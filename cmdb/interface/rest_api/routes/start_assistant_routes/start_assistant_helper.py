# DataGerry - OpenSource Enterprise CMDB
# Copyright (C) 2026 becon GmbH
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as
# published by the Free Software Foundation, either version 3 of the
# License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program. If not, see <https://www.gnu.org/licenses/>.
"""
The rules of the start assistant's decision, apart from the routes so each is unit-testable

``read_decision`` answers what is stored (or the empty answer); ``read_decision_payload`` holds a POST body to its one
key and the known decisions; ``build_decision_document`` stamps who and when; ``holds_start_assistant_rights`` and
``build_offer`` answer whether to offer the assistant (``GET /start_assistant/offer``). Whether the installation is
empty is the configuration import's own precondition, ``reset_scope.has_import_blockers``
"""
from datetime import datetime, timezone
from typing import Any

from flask import abort

from cmdb.manager import SettingsManager
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    DECISION_PAYLOAD_INVALID_MESSAGE,
    START_ASSISTANT_RIGHTS,
    START_ASSISTANT_SETTINGS_SECTION,
    UNKNOWN_DECISION_MESSAGE,
    StartAssistantDecision,
    StartAssistantKey,
    StartAssistantOfferKey,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'build_decision_document',
    'build_offer',
    'holds_start_assistant_rights',
    'read_decision',
    'read_decision_payload',
]


def read_decision(settings_manager: SettingsManager) -> dict[str, Any]:
    """
    Reads the recorded decision, or the answer for "not run yet"

    The answer always carries the three ``StartAssistantKey`` keys; without a stored section each is None. The
    section's own ``_id`` is not part of it

    Args:
        settings_manager (SettingsManager): The tenant's settings manager

    Returns:
        dict[str, Any]: ``{decision, decided_by, decided_at}``
    """
    stored: dict[str, Any] = settings_manager.get_section(START_ASSISTANT_SETTINGS_SECTION) or {}

    return {key.value: stored.get(key.value) for key in StartAssistantKey}


def read_decision_payload(body: Any) -> StartAssistantDecision:
    """
    Holds a POST body to the one key it may carry, and its value to the known decisions

    Args:
        body (Any): The parsed JSON body (None when there is none, or it is not JSON)

    Raises:
        HTTPException: 400 when the body is not an object holding exactly ``decision``, or names an unknown one

    Returns:
        StartAssistantDecision: The decision to record
    """
    if not isinstance(body, dict) or set(body) != {StartAssistantKey.DECISION.value}:
        abort(400, DECISION_PAYLOAD_INVALID_MESSAGE)

    value: Any = body[StartAssistantKey.DECISION.value]

    if not isinstance(value, str) or not StartAssistantDecision.is_valid(value):
        abort(400, UNKNOWN_DECISION_MESSAGE.format(
            decision=value, allowed=', '.join(decision.value for decision in StartAssistantDecision),
        ))

    return StartAssistantDecision(value)


def build_decision_document(
        decision: StartAssistantDecision,
        request_user: CmdbUser,
        decided_at: datetime | None = None) -> dict[str, Any]:
    """
    Builds the stored decision: what, who, when

    Args:
        decision (StartAssistantDecision): The decision
        request_user (CmdbUser): The user recording it
        decided_at (datetime | None): When; now (UTC) when None

    Returns:
        dict[str, Any]: ``{decision, decided_by, decided_at}``
    """
    return {
        StartAssistantKey.DECISION.value: decision.value,
        StartAssistantKey.DECIDED_BY.value: request_user.get_public_id(),
        StartAssistantKey.DECIDED_AT.value: decided_at or datetime.now(timezone.utc),
    }


def holds_start_assistant_rights(request_user: CmdbUser) -> bool:
    """
    Whether the caller may run the start assistant: they hold every right in ``START_ASSISTANT_RIGHTS``

    Args:
        request_user (CmdbUser): The caller

    Returns:
        bool: True when the caller's group holds both rights
    """
    return all(user_has_right(right, request_user) for right in START_ASSISTANT_RIGHTS)


def build_offer(holds_rights: bool, blocked: bool, decision: str | None) -> dict[str, bool]:
    """
    Builds the ``GET /start_assistant/offer`` answer from what decides it

    Without the rights everything is false. With them, a blocked installation (something would refuse an import)
    answers ``reset_required``; an empty one is ``available``, and ``show`` too while nothing was decided - a recorded
    decision stops the assistant from opening by itself but leaves it available

    Args:
        holds_rights (bool): The caller holds ``START_ASSISTANT_RIGHTS``
        blocked (bool): A reset target that blocks an import is not empty (``has_import_blockers``)
        decision (str | None): The recorded decision, None when nothing is recorded

    Returns:
        dict[str, bool]: ``{show, available, reset_required}``
    """
    available: bool = holds_rights and not blocked

    return {
        StartAssistantOfferKey.SHOW.value: available and decision is None,
        StartAssistantOfferKey.AVAILABLE.value: available,
        StartAssistantOfferKey.RESET_REQUIRED.value: holds_rights and blocked,
    }
