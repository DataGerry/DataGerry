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
Implementation of the API routes of the start assistant

The start assistant is offered on an empty installation - empty as the configuration import asks for it
(``reset_scope.has_import_blockers``: no leftover in any reset target that blocks an import), so whatever the
assistant offers, the import accepts. What the user decides there is stored as one settings
section (``START_ASSISTANT_SETTINGS_SECTION``), so the offer can tell "not run yet" from "decided". Two routes:

    - ``GET /start_assistant/offer``: whether to offer the assistant - ``{show, available, reset_required}``.
      AVAILABLE when the caller holds the rights to record a decision and the installation is empty; SHOW (open it
      after login) when it is available and nothing was decided yet; RESET_REQUIRED when the caller holds the rights
      but the installation is not empty. No right of its own; a caller without the rights gets all false and nothing
      is read
    - ``POST /start_assistant/decision``: record one, body ``{"decision": "<StartAssistantDecision>"}``, behind the
      rights to create CmdbTypes and CmdbCategories. Only on an empty installation (else 400: reset first); a
      later decision replaces an earlier one while that still holds - an empty data model chosen first
      can be followed by another choice as long as nothing was created

The configuration reset (``POST /configuration_transfer/reset``) deletes the section, so the decision starts over
"""
from logging import Logger, getLogger
from typing import Any

from flask import abort, request
from werkzeug import Response

from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.manager import SettingsManager
from cmdb.manager.types_manager import TypesManager

from cmdb.models.user_model import CmdbUser
from cmdb.interface.route_utils import (
    handle_manager_errors,
    handle_route_errors,
    insert_request_user,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.framework.configuration_transfer import has_import_blockers
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    DECISION_READ_FAILED_MESSAGE,
    RESET_REQUIRED_MESSAGE,
    START_ASSISTANT_RIGHTS,
    START_ASSISTANT_SETTINGS_SECTION,
    StartAssistantDecision,
    StartAssistantKey,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import (
    build_decision_document,
    build_offer,
    holds_start_assistant_rights,
    read_decision,
    read_decision_payload,
)

from cmdb.errors.database import DocumentGetError
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.types_manager import TypesManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

start_assistant_blueprint = APIBlueprint('start_assistant', __name__, url_prefix='/start_assistant')

# A failed read of the decision, or of what decides whether one may be offered or recorded - one 400 on both routes
DECISION_READ_FAILURES: dict[type[Exception], str] = {
    TypesManagerGetError: DECISION_READ_FAILED_MESSAGE,
    BaseManagerGetError: DECISION_READ_FAILED_MESSAGE,
    DocumentGetError: DECISION_READ_FAILED_MESSAGE,
}

# -------------------------------------------------------------------------------------------------------------------- #

@start_assistant_blueprint.route('/offer', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@handle_route_errors("while checking whether to offer the start assistant")
@handle_manager_errors(DECISION_READ_FAILURES)
def get_start_assistant_offer(request_user: CmdbUser) -> Response:
    """
    Answers whether to offer the start assistant to the caller

    No right of its own - every user asks it after login. ``available``: the caller holds ``base.framework.type.add``
    and ``base.framework.category.add`` and nothing would refuse a configuration import (``has_import_blockers``,
    stopping at the first leftover). ``show``: available, and no decision recorded yet - after one, the assistant no
    longer opens by itself but can still be run while the installation is empty. ``reset_required``: the rights are
    held but the installation is not empty. A caller without the rights gets all false and nothing is read

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when reading what decides it fails, 500 on an unexpected error

    Returns:
        DefaultResponse: ``{show, available, reset_required}``
    """
    if not holds_start_assistant_rights(request_user):
        return DefaultResponse(build_offer(False, False, None)).make_response()

    # Any manager reads the reset targets; the types manager is the one the import's own check uses
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    if has_import_blockers(types_manager):
        return DefaultResponse(build_offer(True, True, None)).make_response()

    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    decision: str | None = read_decision(settings_manager)[StartAssistantKey.DECISION.value]

    return DefaultResponse(build_offer(True, False, decision)).make_response()


@start_assistant_blueprint.route('/decision', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[0])
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[1])
@handle_route_errors("while recording the start assistant decision")
@handle_manager_errors(DECISION_READ_FAILURES)
def record_start_assistant_decision(request_user: CmdbUser) -> Response:
    """
    Records the decision taken in the start assistant

    Asks for ``base.framework.type.add`` and ``base.framework.category.add``. The body is ``{"decision": ...}``, one of
    ``StartAssistantDecision``; nothing may refuse a configuration import (``has_import_blockers``). A decision recorded
    before is replaced - the user may change their mind while the installation is still empty

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 without either right; 400 for a body that is not ``{"decision": <known decision>}``, an
                       installation that is not empty (reset first), or a failed read; 500 on an unexpected error

    Returns:
        DefaultResponse: The recorded decision, ``{decision, decided_by, decided_at}``
    """
    decision: StartAssistantDecision = read_decision_payload(request.get_json(silent=True))

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    if has_import_blockers(types_manager):
        abort(400, RESET_REQUIRED_MESSAGE)

    document: dict[str, Any] = build_decision_document(decision, request_user)
    settings_manager.write(START_ASSISTANT_SETTINGS_SECTION, document)

    LOGGER.info("[record_start_assistant_decision] User %s recorded the start assistant decision '%s'",
                request_user.get_public_id(), decision.value)

    return DefaultResponse(document).make_response()
