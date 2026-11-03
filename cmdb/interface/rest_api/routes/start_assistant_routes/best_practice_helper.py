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
The best-practice models as the start assistant's routes answer them, apart from the routes so each is unit-testable

``build_model_card`` is one model's card in ``GET /start_assistant/models``; ``build_model_details`` adds what
``GET /start_assistant/models/<model_id>`` shows. Both are computed from the model's file (``build_model_preview``)
and its meta section, and judged against the caller's licence: ``missing_features`` are the required features
``feature_locked`` refuses for this installation (on premise: not licensed; in cloud mode none - the subscription
decides there), ``applicable`` means none is missing

Several models can be applied together. ``read_model_selection`` holds the POST body to the models it names (in card
order); ``combine_selection`` brings each to the installation's database version and combines them into one transfer
file (``combine_models``: one entry per name, every id renumbered, every conflict collected).
``build_selection_preview`` is what ``POST /start_assistant/models/preview`` answers about such a selection, writing
nothing; ``apply_best_practice_models`` is what ``POST /start_assistant/models`` does: the licence over every model
(the gates' own 403 - never applied in part), the conflicts (400 naming every one), the configuration import with the
recorded decision as its last write - all or nothing together
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, replace
from logging import Logger, getLogger
from typing import Any

from flask import abort

from cmdb.framework.configuration_transfer import (
    BestPracticeCatalogue,
    BestPracticeModel,
    CombinedModels,
    ModelPreview,
    build_model_preview,
    combine_models,
    find_import_blockers,
)
from cmdb.framework.configuration_transfer.best_practice_constants import MODEL_PROBLEM
from cmdb.manager import SettingsManager, TypesManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked, feature_locked
from cmdb.interface.blueprints.api_blueprint_constants import ERRORS_SEPARATOR
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner import (
    import_transfer_document,
    judge_transfer_document,
    migrate_to_version,
    read_target_version,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    MODEL_NOT_FOUND_MESSAGE,
    SELECTION_CONFLICTS_MESSAGE,
    SELECTION_EMPTY_MESSAGE,
    SELECTION_NOT_IDS_MESSAGE,
    SELECTION_PAYLOAD_INVALID_MESSAGE,
    SELECTION_REPEATED_MESSAGE,
    BestPracticeApplyKey,
    BestPracticeModelKey,
    BestPracticeSelectionKey,
    StartAssistantDecision,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import (
    build_decision_document,
    write_decision_on_ledger,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'abort_if_model_unlicensed',
    'apply_best_practice_models',
    'build_model_card',
    'build_model_details',
    'build_selection_preview',
    'combine_selection',
    'migrate_models',
    'missing_features',
    'read_model_selection',
    'required_features_of',
]

LOGGER: Logger = getLogger(__name__)


def missing_features(required: tuple[str, ...], request_user: CmdbUser) -> list[str]:
    """
    The required features this installation may not use

    Args:
        required (tuple[str, ...]): The ``LicenseFeature`` values a model needs
        request_user (CmdbUser): The caller - the tenant whose licence is asked in cloud mode

    Returns:
        list[str]: Those of them ``feature_locked`` refuses, in the given order
    """
    return [feature for feature in required if feature_locked(LicenseFeature(feature), request_user)]


def build_model_card(model: BestPracticeModel, preview: ModelPreview, request_user: CmdbUser) -> dict[str, Any]:
    """
    One model's card in the selection

    Args:
        model (BestPracticeModel): The model
        preview (ModelPreview): Its preview
        request_user (CmdbUser): The caller, whose licence decides ``missing_features``

    Returns:
        dict[str, Any]: The card (``BestPracticeModelKey``)
    """
    missing: list[str] = missing_features(preview.required_features, request_user)

    return {
        BestPracticeModelKey.MODEL_ID.value: model.model_id,
        BestPracticeModelKey.TITLE.value: model.meta.title,
        BestPracticeModelKey.BADGE.value: model.meta.badge,
        BestPracticeModelKey.SUMMARY.value: model.meta.summary,
        BestPracticeModelKey.COUNTS.value: asdict(preview.counts),
        BestPracticeModelKey.CATEGORY_LABELS.value: [category.label for category in preview.categories],
        BestPracticeModelKey.REQUIRED_FEATURES.value: list(preview.required_features),
        BestPracticeModelKey.MISSING_FEATURES.value: missing,
        BestPracticeModelKey.APPLICABLE.value: not missing,
    }


def build_model_details(model: BestPracticeModel, request_user: CmdbUser) -> dict[str, Any]:
    """
    One model's details: its card, its texts, its categories with their types, sections and fields, its relations

    Args:
        model (BestPracticeModel): The model
        request_user (CmdbUser): The caller, whose licence decides ``missing_features``

    Returns:
        dict[str, Any]: The details (``BestPracticeModelKey``; the tree's keys are the preview dataclasses' fields)
    """
    preview: ModelPreview = build_model_preview(model.document, model.meta)

    return {
        **build_model_card(model, preview, request_user),
        BestPracticeModelKey.DESCRIPTION.value: model.meta.description,
        BestPracticeModelKey.SUITED_FOR.value: list(model.meta.suited_for),
        BestPracticeModelKey.PROFILES.value: list(model.meta.profiles),
        BestPracticeModelKey.CATEGORIES.value: [asdict(category) for category in preview.categories],
        BestPracticeModelKey.UNCATEGORIZED.value: [asdict(type_preview) for type_preview in preview.uncategorized],
        BestPracticeModelKey.RELATIONS.value: [asdict(relation) for relation in preview.relations],
    }


def abort_if_model_unlicensed(required: tuple[str, ...], request_user: CmdbUser) -> None:
    """
    Refuses models that need a feature this installation may not use - with the licence gates' own 403

    Never applied in part: until a community variant exists, a selection with a missing feature is not applied at all

    Args:
        required (tuple[str, ...]): The ``LicenseFeature`` values the models need
        request_user (CmdbUser): The caller - the tenant whose licence is asked in cloud mode

    Raises:
        HTTPException: 403 naming the first missing feature
    """
    for feature in required:
        abort_if_feature_locked(LicenseFeature(feature), request_user)


def read_model_selection(body: Any, catalogue: BestPracticeCatalogue) -> list[BestPracticeModel]:
    """
    Holds a selection body to the models it names: ``{"model_ids": [<model id>, ...]}``

    Args:
        body (Any): The parsed JSON body (None when there is none, or it is not JSON)
        catalogue (BestPracticeCatalogue): The offered models

    Raises:
        HTTPException: 400 for a body that is not an object holding exactly ``model_ids``, a value that is not a list
            of strings, an empty list or an id named twice; 404 for the first id no offered model has

    Returns:
        list[BestPracticeModel]: The named models, in card order
    """
    key: str = BestPracticeSelectionKey.MODEL_IDS.value

    if not isinstance(body, dict) or set(body) != {key}:
        abort(400, SELECTION_PAYLOAD_INVALID_MESSAGE)

    model_ids: Any = body[key]

    if not isinstance(model_ids, list) or not all(isinstance(model_id, str) for model_id in model_ids):
        abort(400, SELECTION_NOT_IDS_MESSAGE.format(values=model_ids))

    if not model_ids:
        abort(400, SELECTION_EMPTY_MESSAGE)

    repeated: list[str] = sorted(model_id for model_id, count in Counter(model_ids).items() if count > 1)

    if repeated:
        abort(400, SELECTION_REPEATED_MESSAGE.format(model_ids=repeated))

    unknown: str | None = next((model_id for model_id in model_ids if catalogue.get(model_id) is None), None)

    if unknown is not None:
        abort(404, MODEL_NOT_FOUND_MESSAGE.format(model_id=unknown))

    return [model for model in catalogue.models if model.model_id in model_ids]


def required_features_of(models: list[BestPracticeModel]) -> tuple[str, ...]:
    """
    The licensed features applying the models together needs - every one any of them needs

    Read off each model's own file, as its card shows it, so the licence is judged before anything is migrated

    Args:
        models (list[BestPracticeModel]): The models

    Returns:
        tuple[str, ...]: The ``LicenseFeature`` values, sorted
    """
    return tuple(sorted({feature for model in models
                         for feature in build_model_preview(model.document, model.meta).required_features}))


def migrate_models(models: list[BestPracticeModel],
                   db_version: int) -> tuple[list[BestPracticeModel], list[str]]:
    """
    Brings each model's file to the installation's database version - a copy, the catalogue keeps its document

    Bundled models may have been exported at different versions; combined, they must speak one

    Args:
        models (list[BestPracticeModel]): The models
        db_version (int): The installation's updater version

    Raises:
        HTTPException: 500 when a migration failed

    Returns:
        tuple[list[BestPracticeModel], list[str]]: The migrated models, and each refused file's problems prefixed
            with its model (its model is then left out)
    """
    migrated_models: list[BestPracticeModel] = []
    problems: list[str] = []

    for model in models:
        migrated, file_problems = migrate_to_version(deepcopy(model.document), db_version)
        problems += [MODEL_PROBLEM.format(model_id=model.model_id, problem=problem) for problem in file_problems]

        if migrated is not None:
            migrated_models.append(replace(model, document=migrated))

    return migrated_models, problems


def combine_selection(models: list[BestPracticeModel], request_user: CmdbUser) -> CombinedModels:
    """
    Combines the selected models into one transfer file in the installation's database version

    Args:
        models (list[BestPracticeModel]): The selected models, in card order
        request_user (CmdbUser): The caller, whose tenant database's version the file is brought to

    Raises:
        HTTPException: 500 when the database records no version or a migration failed

    Returns:
        CombinedModels: The combined file, every conflict and what was merged - a model whose file could not be
            migrated is a conflict, and nothing is combined then
    """
    migrated, problems = migrate_models(models, read_target_version(request_user))

    if problems:
        return CombinedModels({}, models[0].meta, tuple(problems), {})

    return combine_models(migrated)


def build_selection_preview(models: list[BestPracticeModel], request_user: CmdbUser) -> dict[str, Any]:
    """
    What applying the selected models together would create, and everything that stands in its way - nothing written

    The import's own judgement of the combined file is only asked when the models combine; the reset blockers are
    answered either way

    Args:
        models (list[BestPracticeModel]): The selected models, in card order
        request_user (CmdbUser): The caller, whose licence and tenant decide

    Raises:
        HTTPException: 500 when the database records no version or a migration failed

    Returns:
        dict[str, Any]: The preview (``BestPracticeSelectionKey``)
    """
    combined: CombinedModels = combine_selection(models, request_user)
    preview: ModelPreview = build_model_preview(combined.document, combined.meta)
    missing: list[str] = missing_features(required_features_of(models), request_user)
    types_manager: TypesManager = ManagerProvider.get_manager(ManagerType.TYPES, request_user)
    blockers: list[str] = find_import_blockers(types_manager)
    problems: list[str] = [] if combined.conflicts else judge_transfer_document(
        combined.document, request_user, read_target_version(request_user),
    )[1]

    return {
        BestPracticeSelectionKey.MODEL_IDS.value: [model.model_id for model in models],
        BestPracticeSelectionKey.COUNTS.value: asdict(preview.counts),
        BestPracticeSelectionKey.CATEGORY_LABELS.value: [category.label for category in preview.categories],
        BestPracticeSelectionKey.REQUIRED_FEATURES.value: list(required_features_of(models)),
        BestPracticeSelectionKey.MISSING_FEATURES.value: missing,
        BestPracticeSelectionKey.CONFLICTS.value: list(combined.conflicts),
        BestPracticeSelectionKey.MERGED.value: {component: list(names)
                                                for component, names in combined.merged.items()},
        BestPracticeSelectionKey.PROBLEMS.value: problems,
        BestPracticeSelectionKey.RESET_BLOCKERS.value: blockers,
        BestPracticeSelectionKey.APPLICABLE.value: not (missing or combined.conflicts or problems or blockers),
    }


def apply_best_practice_models(models: list[BestPracticeModel], request_user: CmdbUser) -> dict[str, Any]:
    """
    Applies best-practice models together: the licence, the combination, the configuration import, the decision

    In order: every licensed feature any of the models needs (the gates' own 403 - never applied in part); the
    models combined into one file (``combine_selection``), refused with every conflict (400); the combined file through
    ``import_transfer_document`` - every rule of the configuration import holds, the system must be reset (which keeps
    an installation to one apply) and the writes are all or nothing. **The decision is part of the import**:
    ``best_practice_model`` with the models' ids is its last write, inside the configuration lock and on its ledger
    (``write_decision_on_ledger``). Should that write fail, the import is undone with it - the answer is the failure's
    own (500, or the 503 / 423 of a temporary database error) and true: nothing was applied, a retry can succeed. And
    a reset cannot run between the import and the decision

    Args:
        models (list[BestPracticeModel]): The selected models, in card order
        request_user (CmdbUser): The applying user, who becomes the author of every imported document

    Raises:
        HTTPException: 403 for a missing licensed feature; 400 for models that cannot be combined; the import's
            400 / 500 - a failed decision write included, the import undone

    Returns:
        dict[str, Any]: ``{model_ids, imported, decision}`` (``BestPracticeApplyKey``)
    """
    abort_if_model_unlicensed(required_features_of(models), request_user)

    combined: CombinedModels = combine_selection(models, request_user)

    if combined.conflicts:
        abort(400, SELECTION_CONFLICTS_MESSAGE.format(conflicts=ERRORS_SEPARATOR.join(combined.conflicts)))

    model_ids: list[str] = [model.model_id for model in models]
    decision: dict[str, Any] = build_decision_document(
        StartAssistantDecision.BEST_PRACTICE_MODEL, request_user, model_ids=model_ids,
    )
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)

    imported: dict[str, int] = import_transfer_document(
        combined.document, request_user,
        final_write=lambda ledger: write_decision_on_ledger(settings_manager, decision, ledger),
    )

    LOGGER.info("[apply_best_practice_models] User %s applied the best-practice models %s: %s",
                request_user.get_public_id(), model_ids, imported)

    return {
        BestPracticeApplyKey.MODEL_IDS.value: model_ids,
        BestPracticeApplyKey.IMPORTED.value: imported,
        BestPracticeApplyKey.DECISION.value: decision,
    }
