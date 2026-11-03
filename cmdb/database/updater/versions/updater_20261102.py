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
Database update 20261102: the start assistant's decision names its best-practice models as a list

Several best-practice models can be applied together since this version, so the decision the start assistant stores
in the ``start_assistant`` section of ``settings.conf`` names them as ``models``, a list, instead of one ``model``.
This update rewrites a stored section once: a model id becomes a list of that one id, a null stays null (the decision
of an empty data model), and ``model`` is removed.

Re-run safe: only a section still holding ``model`` is touched, and the rewrite removes it - a second run matches
nothing
"""
from logging import Logger, getLogger
from typing import Any

from cmdb.database.updater.base_database_update import BaseDatabaseUpdate

from cmdb.errors.updater import UpdaterException
# -------------------------------------------------------------------------------------------------------------------- #

LOGGER: Logger = getLogger(__name__)

# The literals of this migration are frozen: it must keep meaning what it meant when it shipped
SETTINGS_COLLECTION: str = 'settings.conf'
SECTION_ID_FIELD: str = '_id'
START_ASSISTANT_SECTION: str = 'start_assistant'
OLD_MODEL_FIELD: str = 'model'
NEW_MODELS_FIELD: str = 'models'
STRING_BSON_TYPE: str = 'string'

# The section the update rewrites: the start assistant's decision, still in its old shape
OLD_DECISION_CRITERIA: dict[str, Any] = {
    SECTION_ID_FIELD: START_ASSISTANT_SECTION,
    OLD_MODEL_FIELD: {'$exists': True},
}

# One write: ``models`` is ``[model]`` for a stored model id and null for anything else, then ``model`` is removed
OLD_DECISION_REWRITE: list[dict[str, Any]] = [
    {'$set': {NEW_MODELS_FIELD: {'$cond': [
        {'$eq': [{'$type': f'${OLD_MODEL_FIELD}'}, STRING_BSON_TYPE]},
        [f'${OLD_MODEL_FIELD}'],
        None,
    ]}}},
    {'$unset': OLD_MODEL_FIELD},
]

# ---------------------------------------------- Update20261102 - CLASS ---------------------------------------------- #

class Update20261102(BaseDatabaseUpdate):
    """
    Rewrites the start assistant's stored decision from one ``model`` to a list of ``models``

    Extends: BaseDatabaseUpdate
    """
    def creation_date(self) -> int:
        return 20261102


    def description(self) -> str:
        return "Rewrites the start assistant's stored decision from one model to a list of models"


    def start_update(self) -> None:
        """
        Rewrites the decision when it is still in its old shape, then bumps the version

        Raises:
            UpdaterException: If the rewrite fails
        """
        try:
            rewritten: int = self.dbm.update_many_raw(
                SETTINGS_COLLECTION, self.db_name, OLD_DECISION_CRITERIA, OLD_DECISION_REWRITE,
            ).modified_count

            if rewritten:
                LOGGER.info("[updater_20261102] Rewrote the start assistant's decision to a list of models")

            self.increase_updater_version(self.creation_date())
        except Exception as err:
            raise UpdaterException(err) from err
