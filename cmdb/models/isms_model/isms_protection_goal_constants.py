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
Document keys of an IsmsProtectionGoal

The keys of the ``isms.protectionGoal`` documents, named once, and the driver of the shared
``CmdbDAO`` ``from_data`` / ``to_json``.

``ProtectionGoalKey`` lives in the model layer rather than beside the three goals DataGerry seeds, so
the MODEL layer never imports its own document shape from the database-seeding package. The seed data
imports it from here, the normal direction: predefined data builds model documents. (``RiskMatrixKey``
follows the same rule.)

``PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS`` is what a stored document must carry. ``predefined`` is
deliberately absent from it: the shared ``from_data`` reads with ``data.get()``, and a goal written
without the flag is simply not one DataGerry seeded - the model coerces that to ``False`` rather than
refusing to load it

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'ProtectionGoalKey',
    'PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS',
]


class ProtectionGoalKey(BaseStrEnum):
    """
    Field keys of an IsmsProtectionGoal document

    ``PREDEFINED`` marks the three goals DataGerry seeds (Confidentiality, Integrity, Availability),
    which the routes refuse to delete or rename - everything else is user-created
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    PREDEFINED = 'predefined'


# The key without which a protection goal means nothing: its name
PROTECTION_GOAL_REQUIRED_DOCUMENT_KEYS: list[str] = [
    ProtectionGoalKey.NAME.value,
]
