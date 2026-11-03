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

``write_decision_on_ledger`` records a decision as one write of a ledger - how applying best-practice models makes the
decision part of the import, undone with it - and ``restore_decision`` is its undo
"""
from datetime import datetime, timezone
from typing import Any

from flask import abort

from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import SettingsManager
from cmdb.manager.system_manager.settings_manager import SETTINGS_SECTION_ID_KEY
from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import user_has_right
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    DECISION_PAYLOAD_INVALID_MESSAGE,
    DECISION_WRITE_DESCRIPTION,
    RECORDABLE_DECISIONS,
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
    'restore_decision',
    'write_decision_on_ledger',
]


def read_decision(settings_manager: SettingsManager) -> dict[str, Any]:
    """
    Reads the recorded decision, or the answer for "not run yet"

    The answer always carries every ``StartAssistantKey`` key; without a stored section each is None, and so is a key
    a section stored before it existed lacks (``models`` of an earlier ``empty_data_model``). The section's own ``_id``
    is not part of it

    Args:
        settings_manager (SettingsManager): The tenant's settings manager

    Returns:
        dict[str, Any]: ``{decision, decided_by, decided_at, models}``
    """
    stored: dict[str, Any] = settings_manager.get_section(START_ASSISTANT_SETTINGS_SECTION) or {}

    return {key.value: stored.get(key.value) for key in StartAssistantKey}


def read_decision_payload(body: Any) -> StartAssistantDecision:
    """
    Holds a POST body to the one key it may carry, and its value to the decisions the route records

    ``best_practice_model`` is no such decision: it is recorded by applying the model, so a client cannot claim a model
    it never applied

    Args:
        body (Any): The parsed JSON body (None when there is none, or it is not JSON)

    Raises:
        HTTPException: 400 when the body is not an object holding exactly ``decision``, or names a decision outside
            ``RECORDABLE_DECISIONS``

    Returns:
        StartAssistantDecision: The decision to record
    """
    if not isinstance(body, dict) or set(body) != {StartAssistantKey.DECISION.value}:
        abort(400, DECISION_PAYLOAD_INVALID_MESSAGE)

    value: Any = body[StartAssistantKey.DECISION.value]

    if not isinstance(value, str) or value not in {decision.value for decision in RECORDABLE_DECISIONS}:
        abort(400, UNKNOWN_DECISION_MESSAGE.format(
            decision=value, allowed=', '.join(decision.value for decision in RECORDABLE_DECISIONS),
        ))

    return StartAssistantDecision(value)


def build_decision_document(
        decision: StartAssistantDecision,
        request_user: CmdbUser,
        decided_at: datetime | None = None,
        model_ids: list[str] | None = None) -> dict[str, Any]:
    """
    Builds the stored decision: what, who, when - and which models, for applied best-practice models

    Args:
        decision (StartAssistantDecision): The decision
        request_user (CmdbUser): The user recording it
        decided_at (datetime | None): When; now (UTC) when None
        model_ids (list[str] | None): The applied best-practice models, in card order; None for any other decision

    Returns:
        dict[str, Any]: ``{decision, decided_by, decided_at, models}``
    """
    return {
        StartAssistantKey.DECISION.value: decision.value,
        StartAssistantKey.DECIDED_BY.value: request_user.get_public_id(),
        StartAssistantKey.DECIDED_AT.value: decided_at or datetime.now(timezone.utc),
        StartAssistantKey.MODELS.value: list(model_ids) if model_ids is not None else None,
    }


def restore_decision(settings_manager: SettingsManager, prior: dict[str, Any] | None) -> None:
    """
    Puts the decision section back as it was: removed, then the prior section written again when there was one

    Removed first so a key the newer decision added does not stay behind on the restored one

    Args:
        settings_manager (SettingsManager): The tenant's settings manager
        prior (dict[str, Any] | None): The section as it was stored, ``_id`` included; None when there was none
    """
    settings_manager.delete_section(START_ASSISTANT_SETTINGS_SECTION)

    if prior is not None:
        settings_manager.write(START_ASSISTANT_SETTINGS_SECTION,
                               {key: value for key, value in prior.items() if key != SETTINGS_SECTION_ID_KEY})


def write_decision_on_ledger(settings_manager: SettingsManager, decision: dict[str, Any], ledger: WriteLedger) -> None:
    """
    Records a decision as one write of a ledger - undone, back to the section stored before, when the ledger is

    The stored section is read first and the write recorded before it runs (``WriteLedger.compensated``), so an undo
    restores what was there: nothing, or an earlier decision such as an empty data model

    Args:
        settings_manager (SettingsManager): The tenant's settings manager
        decision (dict[str, Any]): The decision to store (``build_decision_document``)
        ledger (WriteLedger): The ledger the write belongs to

    Raises:
        DocumentGetError: When the stored section could not be read - nothing is written then
        DocumentUpdateError: When the write failed
    """
    prior: dict[str, Any] | None = settings_manager.get_section(START_ASSISTANT_SETTINGS_SECTION)

    ledger.compensated(
        SettingsManager.COLLECTION,
        DECISION_WRITE_DESCRIPTION,
        undo=lambda: restore_decision(settings_manager, prior),
        verify=lambda: settings_manager.get_section(START_ASSISTANT_SETTINGS_SECTION) == prior,
    )
    settings_manager.write(START_ASSISTANT_SETTINGS_SECTION, decision)


def holds_start_assistant_rights(request_user: CmdbUser) -> bool:
    """
    Whether the caller may run the start assistant: they hold every right in ``START_ASSISTANT_RIGHTS``

    Args:
        request_user (CmdbUser): The caller

    Returns:
        bool: True when the caller's group holds both rights
    """
    return all(user_has_right(right, request_user) for right in START_ASSISTANT_RIGHTS)


def build_offer(holds_rights: bool, blocked: bool, decision: str | None, may_import: bool) -> dict[str, bool]:
    """
    Builds the ``GET /start_assistant/offer`` answer from what decides it

    Without the rights everything is false. With them, a blocked installation (something would refuse an import)
    answers ``reset_required``; an empty one is ``available``, and ``show`` too while nothing was decided - a recorded
    decision stops the assistant from opening by itself but leaves it available. ``can_import`` is ``available`` for a
    caller holding the master right only: the import and applying a best-practice model ask for it

    Args:
        holds_rights (bool): The caller holds ``START_ASSISTANT_RIGHTS``
        blocked (bool): A reset target that blocks an import is not empty (``has_import_blockers``)
        decision (str | None): The recorded decision, None when nothing is recorded
        may_import (bool): The caller holds the master right ``base.*`` (``CONFIGURATION_TRANSFER_RIGHT``)

    Returns:
        dict[str, bool]: ``{show, available, reset_required, can_import}``
    """
    available: bool = holds_rights and not blocked

    return {
        StartAssistantOfferKey.SHOW.value: available and decision is None,
        StartAssistantOfferKey.AVAILABLE.value: available,
        StartAssistantOfferKey.RESET_REQUIRED.value: holds_rights and blocked,
        StartAssistantOfferKey.CAN_IMPORT.value: available and may_import,
    }
