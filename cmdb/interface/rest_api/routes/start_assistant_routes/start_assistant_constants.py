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
]

# The rights recording a decision needs: the assistant sets up the data model, it creates CmdbTypes and CmdbCategories
START_ASSISTANT_RIGHTS: tuple[str, ...] = (TypeRight.ADD.value, CategoryRight.ADD.value)

# The settings section holding the decision - its absence means "the start assistant has not run here"
START_ASSISTANT_SETTINGS_SECTION: str = 'start_assistant'


class StartAssistantDecision(BaseStrEnum):
    """
    What a user can decide in the start assistant

    EMPTY_DATA_MODEL: start with an empty data model - nothing imported, nothing created
    """
    EMPTY_DATA_MODEL = 'empty_data_model'


class StartAssistantKey(BaseStrEnum):
    """
    Keys of the decision: the stored settings section, the POST body (DECISION only) and the GET answer

    DECIDED_BY is the public_id of the user who recorded it, DECIDED_AT when (UTC)
    """
    DECISION = 'decision'
    DECIDED_BY = 'decided_by'
    DECIDED_AT = 'decided_at'


class StartAssistantOfferKey(BaseStrEnum):
    """
    Keys of the ``GET /start_assistant/offer`` answer

    AVAILABLE: the caller may run the assistant - they hold ``START_ASSISTANT_RIGHTS`` and the installation is empty in
    the sense the configuration import asks for (``reset_scope.has_import_blockers``: no leftover in any reset target
    that blocks an import), whatever was decided before. SHOW: open it on its own after login - AVAILABLE, and
    nothing decided yet. RESET_REQUIRED: the caller holds the rights, but the installation is not empty - a reset comes
    first. So after an empty data model was chosen the assistant stops opening by itself but stays available until
    something is created; afterwards it asks for a reset
    """
    SHOW = 'show'
    AVAILABLE = 'available'
    RESET_REQUIRED = 'reset_required'


DECISION_PAYLOAD_INVALID_MESSAGE: str = "The body must be a JSON object holding exactly one key: 'decision'!"
UNKNOWN_DECISION_MESSAGE: str = "Unknown decision '{decision}'. Allowed: {allowed}!"
RESET_REQUIRED_MESSAGE: str = (
    "The installation is not empty - reset it before running the start assistant!"
)
DECISION_READ_FAILED_MESSAGE: str = "Failed to read the state of the start assistant!"
