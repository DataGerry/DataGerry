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
      can be followed by another choice as long as nothing was created. Checked and written under the configuration
      lock (400 while an import, apply or reset runs)
    - ``GET /start_assistant/models``: the bundled best-practice models as cards, in card order - counts, category
      chips, the licensed features each needs and whether this installation may apply it. Behind the same rights
    - ``GET /start_assistant/models/<model_id>``: one model's details - its texts, its categories with their types,
      sections and fields (reference targets by name), its relations. Behind the same rights; 404 for an unknown id
    - ``POST /start_assistant/models/preview``: what applying a selection of models together would create and what
      stands in its way (conflicts, missing licences, import problems, reset blockers) - body
      ``{"model_ids": [...]}``, behind the assistant's rights, nothing written
    - ``POST /start_assistant/models``: apply a selection together - same body, behind the master right ``base.*``.
      Refused when the installation is not licensed for a feature any of the models needs, or when the models cannot
      be combined (entries of one name that differ); the combination - one entry per name - is imported through the
      configuration import's own pipeline (a reset system only - one apply per installation); ``best_practice_model``
      recorded with the models' ids once it succeeded

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
    apply_best_practice_models,
    build_model_card,
    build_model_details,
    build_selection_preview,
    read_model_selection,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    CONFIGURATION_TRANSFER_RIGHT,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_helper import (
    configuration_lock,
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

    The emptiness check and the write run under the configuration lock (``configuration_lock``) the import, the
    best-practice apply and the reset take, so none of them can complete in between - an apply's decision is never
    overwritten by a check that saw the installation before it. The lock is taken only once the body is known to be
    usable

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 without either right; 400 for a body that is not ``{"decision": <known decision>}``, while
                       a configuration import, apply or reset holds the lock, for an installation that is not empty
                       (reset first), or a failed read; 500 on an unexpected error

    Returns:
        DefaultResponse: The recorded decision, ``{decision, decided_by, decided_at, models}`` - ``models`` null
    """
    decision: StartAssistantDecision = read_decision_payload(request.get_json(silent=True))

    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    with configuration_lock(request_user):
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


@start_assistant_blueprint.route('/models/preview', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[0])
@start_assistant_blueprint.protect(auth=True, right=START_ASSISTANT_RIGHTS[1])
@handle_route_errors("while previewing a selection of best-practice models")
def preview_best_practice_models(request_user: CmdbUser) -> Response:
    """
    Answers what applying a selection of best-practice models together would create, writing nothing

    Asks for the assistant's rights, like the model list. The body is ``{"model_ids": [...]}``. The answer: the
    models in card order; the counts and category labels of the combination; the licensed features it needs and those
    this installation may not use; the conflicts that keep the models from being combined; per component the names
    several models hold, created once; what the configuration import would refuse in the combined file; what keeps
    the installation from being imported into; and whether the selection may be applied

    Args:
        request_user (CmdbUser): User requesting this data

    Raises:
        HTTPException: 403 without either right; 400 for a body that is not ``{"model_ids": [<distinct ids>]}``;
                       404 for an unknown id; 500 when the database records no version, a migration failed or on an
                       unexpected error

    Returns:
        DefaultResponse: The preview (``BestPracticeSelectionKey``)
    """
    models: list[BestPracticeModel] = read_model_selection(request.get_json(silent=True),
                                                           get_best_practice_catalogue())

    return DefaultResponse(build_selection_preview(models, request_user)).make_response()


@start_assistant_blueprint.route('/models', methods=['POST'])
@insert_request_user
@verify_api_access(required_api_level=ApiLevel.LOCKED)
@start_assistant_blueprint.protect(auth=True, right=CONFIGURATION_TRANSFER_RIGHT)
@handle_route_errors("while applying best-practice models")
def apply_best_practice_models_route(request_user: CmdbUser) -> Response:
    """
    Applies a selection of best-practice models together

    Behind the master right ``base.*``, like the configuration import it runs. The body is ``{"model_ids": [...]}``.
    In order: every id must name an offered model, each once (400 / 404); a feature any of the models needs that this
    installation may not use refuses the whole selection (403, the licence gates' message) - it is never applied in
    part; the models are combined - one entry per name, a second entry of a name dropped when identical - and two
    entries of one name that differ refuse it (400 naming every conflict); the combination is imported through
    ``import_transfer_document``, so the system must be reset (400 naming what blocks it - one apply per installation),
    the file is judged completely and the writes are all or nothing - the decision ``best_practice_model`` with the
    models' ids included, as the import's last write: a failed decision undoes the import, so whatever the answer, it
    is true of what is stored

    Args:
        request_user (CmdbUser): The applying user, who becomes the author of every imported document

    Raises:
        HTTPException: 403 without ``base.*`` or for a missing licensed feature; 400 for a body that is not
                       ``{"model_ids": [<distinct ids>]}``, models that cannot be combined, a system that is not reset
                       or a file the import refuses; 404 for an unknown id; 500 when a write failed - the decision's
                       included - and was undone (503 / 423 for a temporary database error, through the app's
                       handlers: a retry can succeed)

    Returns:
        DefaultResponse: ``{model_ids, imported, decision}`` (``BestPracticeApplyKey``)
    """
    models: list[BestPracticeModel] = read_model_selection(request.get_json(silent=True),
                                                           get_best_practice_catalogue())

    return DefaultResponse(apply_best_practice_models(models, request_user)).make_response()
