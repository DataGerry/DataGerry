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
section (``START_ASSISTANT_SETTINGS_SECTION``), so the offer can tell "not run yet" from "decided". The routes:

    - ``GET /start_assistant/offer``: whether to offer the assistant - ``{show, available, reset_required,
      can_import}``. AVAILABLE when the caller holds the rights to record a decision and the installation is empty;
      SHOW (open it after login) when it is available and nothing was decided yet; RESET_REQUIRED when the caller
      holds the rights but the installation is not empty; CAN_IMPORT when it is available to a caller holding
      ``base.*``, the right the import and a best-practice model ask for. No right of its own; a caller without the
      rights gets all false and nothing is read
    - ``POST /start_assistant/decision``: record one, body ``{"decision": "<StartAssistantDecision>"}``, behind the
      rights to create CmdbTypes and CmdbCategories. Only on an empty installation (else 400: reset first); a
      later decision replaces an earlier one while that still holds - an empty data model chosen first
      can be followed by another choice as long as nothing was created
    - ``GET /start_assistant/models``: the bundled best-practice models as cards, in card order - counts, category
      chips, the licensed features each needs and whether this installation may apply it. Behind the same rights
    - ``GET /start_assistant/models/<model_id>``: one model's details - its texts, its categories with their types,
      sections and fields (reference targets by name), its relations. Behind the same rights; 404 for an unknown id
    - ``POST /start_assistant/models/<model_id>``: apply one - behind the master right ``base.*``. Refused when the
      installation is not licensed for a feature the model needs; imported through the configuration import's own
      pipeline (a reset system only - one model per installation); ``best_practice_model`` recorded once it succeeded

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
    user_has_right,
    verify_api_access,
)
from cmdb.interface.rest_api.api_level_enum import ApiLevel
from cmdb.interface.blueprints import APIBlueprint
from cmdb.interface.rest_api.responses import DefaultResponse
from cmdb.framework.configuration_transfer import (
    BestPracticeModel,
    build_model_preview,
    get_best_practice_catalogue,
    has_import_blockers,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    DECISION_READ_FAILED_MESSAGE,
    MODEL_NOT_FOUND_MESSAGE,
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
from cmdb.interface.rest_api.routes.start_assistant_routes.best_practice_helper import (
    apply_best_practice_model,
    build_model_card,
    build_model_details,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_TRANSFER_RIGHT,
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
    held but the installation is not empty. ``can_import``: available, and the caller holds the master right
    ``base.*`` - what the import and applying a best-practice model ask for; only read when available. A caller
    without the rights gets all false and nothing is read

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 400 when reading what decides it fails, 500 on an unexpected error

    Returns:
        DefaultResponse: ``{show, available, reset_required, can_import}``
    """
    if not holds_start_assistant_rights(request_user):
        return DefaultResponse(build_offer(False, False, None, False)).make_response()

    # Any manager reads the reset targets; the types manager is the one the import's own check uses
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)

    if has_import_blockers(types_manager):
        return DefaultResponse(build_offer(True, True, None, False)).make_response()

    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    decision: str | None = read_decision(settings_manager)[StartAssistantKey.DECISION.value]

    may_import: bool = user_has_right(CONFIGURATION_TRANSFER_RIGHT, request_user)

    return DefaultResponse(build_offer(True, False, decision, may_import)).make_response()


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

# -------------------------------------------------------------------------------------------------------------------- #
#                                                BEST-PRACTICE MODELS                                                  #
# -------------------------------------------------------------------------------------------------------------------- #

@start_assistant_blueprint.route('/models', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[0])
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[1])
@handle_route_errors("while listing the best-practice models")
def get_best_practice_models(request_user: CmdbUser) -> Response:
    """
    Lists the bundled best-practice models the start assistant offers, as cards in card order

    Asks for ``base.framework.type.add`` and ``base.framework.category.add``, the assistant's rights. Each card carries
    the model's id, title, badge and summary, its counts and category labels - computed from its file - the licensed
    features applying it needs, those of them this installation may not use and whether it may be applied. A model
    pair that cannot be offered is not listed (the catalogue leaves it out and logs it)

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 without either right, 500 on an unexpected error

    Returns:
        DefaultResponse: The cards (``BestPracticeModelKey``)
    """
    return DefaultResponse([
        build_model_card(model, build_model_preview(model.document, model.meta), request_user)
        for model in get_best_practice_catalogue().models
    ]).make_response()


@start_assistant_blueprint.route('/models/<string:model_id>', methods=['GET'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[0])
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[1])
@handle_route_errors("while reading the best-practice model '{model_id}'")
def get_best_practice_model(model_id: str, request_user: CmdbUser) -> Response:
    """
    Answers one best-practice model's details

    Asks for the assistant's rights. The card's fields plus the description, who the model suits, the profiles it was
    built from, its categories with their types, sections and fields (every reference target resolved to the type it
    names), the types no category holds and its relations

    Args:
        model_id (str): The model's id - its file name without ``.json``
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 without either right, 404 when no offered model has the id, 500 on an unexpected error

    Returns:
        DefaultResponse: The details (``BestPracticeModelKey``)
    """
    model: BestPracticeModel | None = get_best_practice_catalogue().get(model_id)

    if model is None:
        abort(404, MODEL_NOT_FOUND_MESSAGE.format(model_id=model_id))

    return DefaultResponse(build_model_details(model, request_user)).make_response()


@start_assistant_blueprint.route('/models/<string:model_id>', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@start_assistant_blueprint.protect(auth=True, right=CONFIGURATION_TRANSFER_RIGHT)
@handle_route_errors("while applying the best-practice model '{model_id}'")
def apply_best_practice_model_route(model_id: str, request_user: CmdbUser) -> Response:
    """
    Applies one best-practice model to the installation

    Behind the master right ``base.*``, like the configuration import it runs. No body. In order: the model
    must be offered (404); a feature it needs that this installation may not use refuses it (403, the licence gates'
    message) - it is never applied in part; its file is imported through ``import_transfer_document``, so the system
    must be reset (400 naming what blocks it - one model per installation), the file is judged completely and the
    writes are all or nothing; then ``best_practice_model`` is recorded with the model's id

    Args:
        model_id (str): The model's id - its file name without ``.json``
        request_user (CmdbUser): The applying user, who becomes the author of every imported document

    Raises:
        HTTPException: 403 without ``base.*`` or for a missing licensed feature, 404 for an
                       unknown id, 400 for a system that is not reset or a file the import refuses, 500 when a write
                       failed (undone) or the decision could not be recorded (the model stays imported)

    Returns:
        DefaultResponse: ``{model_id, imported, decision}`` (``BestPracticeApplyKey``)
    """
    model: BestPracticeModel | None = get_best_practice_catalogue().get(model_id)

    if model is None:
        abort(404, MODEL_NOT_FOUND_MESSAGE.format(model_id=model_id))

    return DefaultResponse(apply_best_practice_model(model, request_user)).make_response()
