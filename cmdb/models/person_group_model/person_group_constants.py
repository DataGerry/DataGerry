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
Document keys of a CmdbPersonGroup

The keys of the ``management.personGroup`` documents, named once - they were spelled out as bare
literals in the model's ``from_data``, its ``to_json``, the Cerberus schema and both membership
cascades.

``PERSON_GROUP_OPTIONAL_TEXT_KEYS`` and ``PERSON_GROUP_LIST_KEYS`` name the keys the model coerces
instead of storing null - see the same block in ``person_constants``: a stored
``group_members: null`` made the update route read ``set(None)`` and answer 500, and the schema types
the key ``list``, so the document could not be sent back unchanged either

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonGroupKey',
    'PERSON_GROUP_OPTIONAL_TEXT_KEYS',
    'PERSON_GROUP_LIST_KEYS',
]


class PersonGroupKey(BaseStrEnum):
    """
    Field keys of a CmdbPersonGroup document
    """
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    GROUP_MEMBERS = 'group_members'
    EMAIL = 'email'


# The optional free-text keys: absent or null becomes the empty string, never null
PERSON_GROUP_OPTIONAL_TEXT_KEYS: tuple[str, ...] = (
    PersonGroupKey.EMAIL.value,
)

# The list-valued keys: absent or null becomes the empty list, never null
PERSON_GROUP_LIST_KEYS: tuple[str, ...] = (
    PersonGroupKey.GROUP_MEMBERS.value,
)
