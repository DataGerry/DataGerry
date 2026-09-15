# DATAGERRY - OpenSource Enterprise CMDB
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
Implementation of IsmsProtectionGoal in DataGerry - ISMS

An IsmsProtectionGoal is one of the objectives a risk is assessed against (collection
``isms.protectionGoal``). DataGerry seeds three - Confidentiality, Integrity, Availability - and marks
them ``predefined``; the routes refuse to delete or rename those, everything else is user-created.

**``predefined`` is a two-state flag, and an absent value means False.** The shared ``from_data`` reads
with ``data.get()``, so a goal stored without the key would otherwise load as None and serialise into a
document its own schema rejects - the flag is coerced instead, which is also what its absence means: a
goal DataGerry did not seed.

``ProtectionGoalKey`` names the document's keys and drives the shared ``CmdbDAO`` ``from_data`` /
``to_json``, so this model defines neither
"""
from typing import Any

from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.models.isms_model.isms_protection_goal_constants import (
    PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS,
    ProtectionGoalKey,
)

from cmdb.class_schema.isms_model.isms_protection_goal_schema import get_isms_protection_goal_schema

from cmdb.errors.models.isms_protection_goal import (
    IsmsProtectionGoalInitError,
    IsmsProtectionGoalInitFromDataError,
    IsmsProtectionGoalToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #
#                                              IsmsProtectionGoal - CLASS                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class IsmsProtectionGoal(CmdbDAO):
    """
    Implementation of IsmsProtectionGoal

    Extends: CmdbDAO
    """
    COLLECTION = "isms.protectionGoal"

    SCHEMA: dict[str, Any] = get_isms_protection_goal_schema()

    # The document's keys drive the shared from_data / to_json on CmdbDAO, so this model has neither;
    # REQUIRED_INIT_KEYS is what keeps from_data refusing a document that carries no name
    KEYS = ProtectionGoalKey
    REQUIRED_INIT_KEYS: list[str] = PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS
    INIT_FROM_DATA_ERROR = IsmsProtectionGoalInitFromDataError
    TO_JSON_ERROR = IsmsProtectionGoalToJsonError

    def __init__(
            self,
            *,
            public_id: int,
            name: str,
            predefined: bool | None = False,
        ) -> None:
        """
        Initialises an IsmsProtectionGoal

        Keyword-only, because CmdbDAO.__new__ looks for public_id in **kwargs and runs before this:
        a positional call could never have worked

        Args:
            public_id (int): public_id of the IsmsProtectionGoal
            name (str): The name of the IsmsProtectionGoal
            predefined (bool, optional): True for the goals DataGerry seeds. An absent or null value
                becomes False - the schema takes a boolean, and a goal nobody marked as seeded is
                user-created

        Raises:
            IsmsProtectionGoalInitError: When the IsmsProtectionGoal could not be initialised
        """
        try:
            self.name = name
            self.predefined = bool(predefined)

            super().__init__(public_id=public_id)
        except Exception as err:
            raise IsmsProtectionGoalInitError(err) from err
