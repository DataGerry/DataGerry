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
Constants of the LocationsManager's aggregation pipelines

The document keys of a CmdbLocation live in ``cmdb.models.location_model.location_constants``
(``LocationKey``); what is named here belongs to the manager's queries instead: the array fields the
``$graphLookup`` stages write their results into, the MongoDB-owned ``_id`` key and the regex option
flags of the tree search
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CASE_INSENSITIVE_REGEX_OPTIONS',
    'LocationLookupField',
    'MONGO_ID_KEY',
]

# The key MongoDB owns on every document: excluded from the pipeline output (the find-based reads
# drop it in the database layer already) and reused as the '_id' of a $group stage
MONGO_ID_KEY: str = '_id'

# Only 'i' (case-insensitive): the tree search escapes the user's input to a literal substring, so
# the multi-line / dot-all flags of Builder.regex_'s default would have nothing to act on
CASE_INSENSITIVE_REGEX_OPTIONS: str = 'i'


class LocationLookupField(BaseStrEnum):
    """Array fields the CmdbLocation $graphLookup stages write their reachable documents into"""
    ANCESTORS = 'ancestors'
    DESCENDANTS = 'descendants'
