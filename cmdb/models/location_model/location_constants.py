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
Key and identity constants of a CmdbLocation

These live in the model layer because every layer consumes them: the predefined-data seeding in
``cmdb/database``, ``LocationsManager``, the CmdbLocation routes and their helper, the Rack hooks and
the type helper. The seed package's ``predefined_data_constants`` module held them once and is gone,
which meant the interface layer imported a document-key enum *upward* from the database layer; the
model is the one place all of them can depend on downward

``LocationKey`` names the document keys, ``RootLocationDefault`` the identity and sentinel values of
the synthetic root node and ``CmdbLocationDefault`` the fallbacks for the two optional render keys.
LocationKey extends / behaves as a plain string, so members compare equal to their value for dict
construction, lookup and JSON/BSON serialization
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CmdbLocationDefault',
    'LocationKey',
    'RootLocationDefault',
]


class LocationKey(BaseStrEnum):
    """Document keys of a CmdbLocation"""
    PUBLIC_ID = 'public_id'
    NAME = 'name'
    PARENT = 'parent'
    OBJECT_ID = 'object_id'
    TYPE_ID = 'type_id'
    TYPE_LABEL = 'type_label'
    TYPE_ICON = 'type_icon'
    TYPE_SELECTABLE = 'type_selectable'


class RootLocationDefault:
    """
    Identity and sentinel values of the synthetic CmdbLocations root document

    PUBLIC_ID is the fixed root id. NO_PARENT / NO_OBJECT / NO_TYPE are the 0 sentinels marking the
    root as top-of-tree and not backed by a real object or type. NAME doubles as the type label,
    and ICON / SELECTABLE complete the root's render metadata.
    """
    PUBLIC_ID: int = 1
    NAME: str = 'Root'
    NO_PARENT: int = 0
    NO_OBJECT: int = 0
    NO_TYPE: int = 0
    ICON: str = 'fas fa-globe'
    SELECTABLE: bool = True


class CmdbLocationDefault:
    """
    Fallback values for the optional render keys of a CmdbLocation

    A CmdbLocation document may omit 'type_icon' and 'type_selectable' (both carry a default in
    CmdbLocation.__init__ / from_data and in the Cerberus schema). Any code that reads a raw
    location document instead of going through the model applies the same two fallbacks from here,
    so a document-level read and a model round trip answer with the identical key set
    """
    TYPE_ICON: str = 'fas fa-cube'
    TYPE_SELECTABLE: bool = True
