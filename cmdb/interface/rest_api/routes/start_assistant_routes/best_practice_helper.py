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
and its description file, and judged against the caller's licence: ``missing_features`` are the required features
``feature_locked`` refuses for this installation (on premise: not licensed; in cloud mode none - the subscription
decides there), ``applicable`` means none is missing

``apply_best_practice_model`` is what ``POST /start_assistant/models/<model_id>`` does: the licence (the gates' own
403), the configuration import, the recorded decision
"""
from copy import deepcopy
from dataclasses import asdict
from logging import Logger, getLogger
from typing import Any

from cmdb.framework.configuration_transfer import BestPracticeModel, ModelPreview, build_model_preview
from cmdb.manager import SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.cmdb_license.license_guard import abort_if_feature_locked, feature_locked
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner import (
    import_transfer_document,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_constants import (
    START_ASSISTANT_SETTINGS_SECTION,
    BestPracticeApplyKey,
    BestPracticeModelKey,
    StartAssistantDecision,
)
from cmdb.interface.rest_api.routes.start_assistant_routes.start_assistant_helper import build_decision_document
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'abort_if_model_unlicensed',
    'apply_best_practice_model',
    'build_model_card',
    'build_model_details',
    'missing_features',
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
    Refuses a model that needs a feature this installation may not use - with the licence gates' own 403

    Never applied in part: until a community variant exists, a model with a missing feature is not applied at all

    Args:
        required (tuple[str, ...]): The ``LicenseFeature`` values the model needs
        request_user (CmdbUser): The caller - the tenant whose licence is asked in cloud mode

    Raises:
        HTTPException: 403 naming the first missing feature
    """
    for feature in required:
        abort_if_feature_locked(LicenseFeature(feature), request_user)


def apply_best_practice_model(model: BestPracticeModel, request_user: CmdbUser) -> dict[str, Any]:
    """
    Applies a best-practice model: the licence, the configuration import, then the recorded decision

    The model's file goes through ``import_transfer_document`` - every rule of the configuration import holds, the
    system must be reset (which is what keeps an installation to one model) and the writes are all or nothing. The
    import works on a copy: the catalogue keeps its document for the next request. Only once the import succeeded is
    ``best_practice_model`` recorded with the model's id; should that write fail, the model stays imported (the 500
    says so) and the offer answers "reset required" like after any other import

    Args:
        model (BestPracticeModel): The model to apply
        request_user (CmdbUser): The administrator account

    Raises:
        HTTPException: 403 for a missing licensed feature; the import's 400 / 500

    Returns:
        dict[str, Any]: ``{model_id, imported, decision}`` (``BestPracticeApplyKey``)
    """
    preview: ModelPreview = build_model_preview(model.document, model.meta)
    abort_if_model_unlicensed(preview.required_features, request_user)

    imported: dict[str, int] = import_transfer_document(deepcopy(model.document), request_user)

    decision: dict[str, Any] = build_decision_document(
        StartAssistantDecision.BEST_PRACTICE_MODEL, request_user, model_id=model.model_id,
    )
    settings_manager: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    settings_manager.write(START_ASSISTANT_SETTINGS_SECTION, decision)

    LOGGER.info("[apply_best_practice_model] User %s applied the best-practice model '%s': %s",
                request_user.get_public_id(), model.model_id, imported)

    return {
        BestPracticeApplyKey.MODEL_ID.value: model.model_id,
        BestPracticeApplyKey.IMPORTED.value: imported,
        BestPracticeApplyKey.DECISION.value: decision,
    }
