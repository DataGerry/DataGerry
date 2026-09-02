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
Document keys and index names of a CmdbExtendableOption

Owned by the model layer because every layer consumes them: the predefined-data factories and the
database updaters build option documents, the REST routes read request bodies with the same keys,
and the model itself names its indexes from here. Two separate copies of this enum existed before
(``cmdb.database.predefined_data.predefined_data_constants`` and the routes' own
``extendable_options_constants``) - the note in the former asked for exactly this move.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class ExtendableOptionKey(BaseStrEnum):
    """Document / request-body keys of a CmdbExtendableOption"""
    PUBLIC_ID = 'public_id'
    VALUE = 'value'
    OPTION_TYPE = 'option_type'
    PREDEFINED = 'predefined'


# Name of the unique compound index on (option_type, value) - the actual duplicate guarantee.
# Shared with updater_20260902, which builds it on databases that predate the declaration
OPTION_TYPE_VALUE_INDEX_NAME: str = 'option_type-value'

# Name of the non-unique 'option_type' index this collection carried until 2026-09-02. Kept as a
# constant because updater_20260902 has to drop it by name on existing databases: the compound index
# above has option_type as its prefix, so it already serves every query the old one served
LEGACY_OPTION_TYPE_INDEX_NAME: str = 'option_type'
