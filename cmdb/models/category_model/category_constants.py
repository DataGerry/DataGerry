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
Constants for the CmdbCategory domain

``CategoryKey`` enumerates the persisted top-level document keys of a CmdbCategory
(collection ``framework.categories``), ``CategoryMetaKey`` the keys nested under its
'meta' sub-document. Use these members instead of bare string literals when constructing
queries, updates or (de)serialisation against category documents so a typo becomes an
AttributeError instead of a silently ignored key. The shared 'public_id' key is covered
by CmdbObjectKey.PUBLIC_ID (the project-wide precedent for document identity keys)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class CategoryKey(BaseStrEnum):
    """
    Persisted top-level document keys of a CmdbCategory

    CREATION_TIME is stamped by the insert route (it is not part of the validation schema)
    but persists on the document, so it belongs to the document-key enum
    """
    NAME = 'name'
    LABEL = 'label'
    META = 'meta'
    PARENT = 'parent'
    TYPES = 'types'
    CREATION_TIME = 'creation_time'


class CategoryMetaKey(BaseStrEnum):
    """
    Keys of the 'meta' sub-document of a CmdbCategory
    """
    ICON = 'icon'
    ORDER = 'order'
