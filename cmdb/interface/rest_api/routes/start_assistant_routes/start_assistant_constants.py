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
Constants of the start assistant REST routes

The start assistant is offered on an empty installation - empty as the configuration import defines it, so whatever
it offers the import accepts. What the user decides there is stored as one settings
section (``START_ASSISTANT_SETTINGS_SECTION``) holding the ``StartAssistantKey`` values; no section means the
assistant has not run. Recording a decision asks for the rights to create CmdbTypes and CmdbCategories
(``START_ASSISTANT_RIGHTS``) - the assistant's job is to set up the data model
"""
from cmdb.utils import BaseStrEnum
from cmdb.models.type_model.type_constants import TypeRight
from cmdb.interface.rest_api.routes.framework_routes.cmdb_categories.categories_constants import CategoryRight
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'START_ASSISTANT_RIGHTS',
    'START_ASSISTANT_SETTINGS_SECTION',
    'StartAssistantDecision',
    'StartAssistantKey',
    'StartAssistantOfferKey',
    'DECISION_PAYLOAD_INVALID_MESSAGE',
    'UNKNOWN_DECISION_MESSAGE',
    'RESET_REQUIRED_MESSAGE',
    'DECISION_READ_FAILED_MESSAGE',
    'DECISION_WRITE_DESCRIPTION',
    'BestPracticeModelKey',
    'BestPracticeApplyKey',
    'BestPracticeSelectionKey',
    'MODEL_NOT_FOUND_MESSAGE',
    'SELECTION_PAYLOAD_INVALID_MESSAGE',
    'SELECTION_EMPTY_MESSAGE',
    'SELECTION_NOT_IDS_MESSAGE',
    'SELECTION_REPEATED_MESSAGE',
    'SELECTION_CONFLICTS_MESSAGE',
    'RECORDABLE_DECISIONS',
]

# The rights recording a decision needs: the assistant sets up the data model, it creates CmdbTypes and CmdbCategories
START_ASSISTANT_RIGHTS: tuple[str, ...] = (TypeRight.ADD.value, CategoryRight.ADD.value)

# The settings section holding the decision - its absence means "the start assistant has not run here"
START_ASSISTANT_SETTINGS_SECTION: str = 'start_assistant'


class StartAssistantDecision(BaseStrEnum):
    """
    What a user can decide in the start assistant

    EMPTY_DATA_MODEL: start with an empty data model - nothing imported, nothing created (recorded through
    ``POST /start_assistant/decision``). BEST_PRACTICE_MODEL: one or more bundled best-practice models were applied -
    recorded by ``POST /start_assistant/models`` once the import succeeded, never through the decision route
    """
    EMPTY_DATA_MODEL = 'empty_data_model'
    BEST_PRACTICE_MODEL = 'best_practice_model'


# The decisions ``POST /start_assistant/decision`` records; any other is recorded by the step that carries it out
RECORDABLE_DECISIONS: tuple[StartAssistantDecision, ...] = (StartAssistantDecision.EMPTY_DATA_MODEL,)


class StartAssistantKey(BaseStrEnum):
    """
    Keys of the decision: the stored settings section, the POST body (DECISION only) and the GET answer

    DECIDED_BY is the public_id of the user who recorded it, DECIDED_AT when (UTC); MODELS the ids of the applied
    best-practice models in card order, None for any other decision
    """
    DECISION = 'decision'
    DECIDED_BY = 'decided_by'
    DECIDED_AT = 'decided_at'
    MODELS = 'models'


class StartAssistantOfferKey(BaseStrEnum):
    """
    Keys of the ``GET /start_assistant/offer`` answer

    AVAILABLE: the caller may run the assistant - they hold ``START_ASSISTANT_RIGHTS`` and the installation is empty in
    the sense the configuration import asks for (``reset_scope.has_import_blockers``: no leftover in any reset target
    that blocks an import), whatever was decided before. SHOW: open it on its own after login - AVAILABLE, and
    nothing decided yet. RESET_REQUIRED: the caller holds the rights, but the installation is not empty - a reset comes
    first. So after an empty data model was chosen the assistant stops opening by itself but stays available until
    something is created; afterwards it asks for a reset. CAN_IMPORT: AVAILABLE, and the caller holds the master
    right ``base.*`` - what the configuration import and applying a best-practice model ask for, so the assistant
    offers neither to anyone they would refuse
    """
    SHOW = 'show'
    AVAILABLE = 'available'
    RESET_REQUIRED = 'reset_required'
    CAN_IMPORT = 'can_import'


DECISION_PAYLOAD_INVALID_MESSAGE: str = "The body must be a JSON object holding exactly one key: 'decision'!"
UNKNOWN_DECISION_MESSAGE: str = "Unknown decision '{decision}'. Allowed: {allowed}!"
RESET_REQUIRED_MESSAGE: str = (
    "The installation is not empty - reset it before running the start assistant!"
)
DECISION_READ_FAILED_MESSAGE: str = "Failed to read the state of the start assistant!"

# What the import's ledger calls the decision write of an apply - named by an undo that could not take it back
DECISION_WRITE_DESCRIPTION: str = "the start assistant's decision recorded"


class BestPracticeModelKey(BaseStrEnum):
    """
    Keys of a best-practice model in ``GET /start_assistant/models`` (the card) and ``/models/<id>`` (the details)

    The card: MODEL_ID (the id to ask the details and to apply it by), TITLE, BADGE, SUMMARY, COUNTS (``categories``,
    ``types``, ``fields``, ``relations``), CATEGORY_LABELS (the chips), REQUIRED_FEATURES (the ``LicenseFeature`` values
    applying it needs), MISSING_FEATURES (those of them this installation is not licensed for) and APPLICABLE (none is
    missing). The details add DESCRIPTION, SUITED_FOR, PROFILES, CATEGORIES (each with its types, their sections and
    fields), UNCATEGORIZED (the types no category holds) and RELATIONS
    """
    MODEL_ID = 'model_id'
    TITLE = 'title'
    BADGE = 'badge'
    SUMMARY = 'summary'
    COUNTS = 'counts'
    CATEGORY_LABELS = 'category_labels'
    REQUIRED_FEATURES = 'required_features'
    MISSING_FEATURES = 'missing_features'
    APPLICABLE = 'applicable'
    DESCRIPTION = 'description'
    SUITED_FOR = 'suited_for'
    PROFILES = 'profiles'
    CATEGORIES = 'categories'
    UNCATEGORIZED = 'uncategorized'
    RELATIONS = 'relations'


MODEL_NOT_FOUND_MESSAGE: str = "No best-practice model with the ID '{model_id}' exists!"


# The body of ``POST /start_assistant/models`` and ``POST /start_assistant/models/preview``: the models to apply
SELECTION_PAYLOAD_INVALID_MESSAGE: str = "The body must be a JSON object holding exactly one key: 'model_ids'!"
SELECTION_EMPTY_MESSAGE: str = "'model_ids' must name at least one best-practice model!"
SELECTION_NOT_IDS_MESSAGE: str = "'model_ids' must be a list of model ID strings: {values}"
SELECTION_REPEATED_MESSAGE: str = "'model_ids' names a model more than once: {model_ids}"
SELECTION_CONFLICTS_MESSAGE: str = "The selected best-practice models cannot be combined: {conflicts}"


class BestPracticeSelectionKey(BaseStrEnum):
    """
    Keys of a selection of best-practice models: the POST body (MODEL_IDS only) and the preview's answer

    MODEL_IDS the selected models in card order; COUNTS, CATEGORY_LABELS and REQUIRED_FEATURES / MISSING_FEATURES as a
    card has them, for what the combination creates; CONFLICTS why the models cannot be combined (entries of one name
    that differ, a type in two categories, a model's own unresolved ids); MERGED per component the names several
    models hold, created once; PROBLEMS what the configuration import would refuse in the combined file (judged only
    without conflicts); RESET_BLOCKERS what keeps the installation from being imported into; APPLICABLE none of these
    """
    MODEL_IDS = 'model_ids'
    COUNTS = 'counts'
    CATEGORY_LABELS = 'category_labels'
    REQUIRED_FEATURES = 'required_features'
    MISSING_FEATURES = 'missing_features'
    CONFLICTS = 'conflicts'
    MERGED = 'merged'
    PROBLEMS = 'problems'
    RESET_BLOCKERS = 'reset_blockers'
    APPLICABLE = 'applicable'


class BestPracticeApplyKey(BaseStrEnum):
    """
    Keys of the ``POST /start_assistant/models`` answer

    MODEL_IDS the applied models in card order, IMPORTED the number of documents imported per component, DECISION the
    recorded decision (``StartAssistantKey``)
    """
    MODEL_IDS = 'model_ids'
    IMPORTED = 'imported'
    DECISION = 'decision'
