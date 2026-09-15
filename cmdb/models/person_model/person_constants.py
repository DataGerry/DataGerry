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
Document keys of a CmdbPerson

The keys of the ``management.person`` documents, named once - they were spelled out as bare literals
in the model's ``from_data``, its ``to_json``, the Cerberus schema and both membership cascades.

``OPTIONAL_TEXT_KEYS`` and ``LIST_KEYS`` name the keys the model coerces instead of storing null. A
CmdbPerson document must never carry null in them: the Cerberus schema types them ``string`` /
``list``, so a document that did could not be sent back unchanged - the model would be writing values
its own schema refuses on the way in. The constructor coerces (``or ''`` / ``or []``) and
``updater_20260909`` converged what was already stored

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo filter
key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'PersonKey',
    'PERSON_OPTIONAL_TEXT_KEYS',
    'PERSON_LIST_KEYS',
]


class PersonKey(BaseStrEnum):
    """
    Field keys of a CmdbPerson document
    """
    PUBLIC_ID = 'public_id'
    DISPLAY_NAME = 'display_name'
    FIRST_NAME = 'first_name'
    LAST_NAME = 'last_name'
    PHONE_NUMBER = 'phone_number'
    EMAIL = 'email'
    GROUPS = 'groups'


# The optional free-text keys: absent or null becomes the empty string, never null
PERSON_OPTIONAL_TEXT_KEYS: tuple[str, ...] = (
    PersonKey.PHONE_NUMBER.value,
    PersonKey.EMAIL.value,
)

# The list-valued keys: absent or null becomes the empty list, never null
PERSON_LIST_KEYS: tuple[str, ...] = (
    PersonKey.GROUPS.value,
)
