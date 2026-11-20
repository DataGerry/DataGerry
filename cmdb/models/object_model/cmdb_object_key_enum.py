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
Scope-specific dict-key enums for CmdbObject and its embedded structures

A CmdbObject document is a nested dict: the top-level holds identity and reference fields
plus the 'fields' list and the 'multi_data_sections' list; each entry inside those lists is
itself a small dict with its own keyset. Reading or writing these structures with bare string
literals invites typos that silently fail. Use these scope-specific enums instead, picking
the one that matches where in the structure the key lives. All of them extend BaseStrEnum so
members are interchangeable with their string values for dict lookup, equality and JSON
serialization, and inherit a shared is_valid() classmethod — mirroring the pattern of
FieldKey / SectionKey / TypeSchemaKey for CmdbType schemas
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #


class CmdbObjectKey(BaseStrEnum):
    """
    Top-level dict keys of a CmdbObject document

    These appear at the outermost level of the document and reference identity, type linkage,
    the active flag, the top-level field list, the multi-data-section list and the lifecycle timestamps.
    SYSTEM_REF links an object to the user-management record the sync mirrors into it (a user or a user group, see
    ``CmdbObjectSystemRefKey``); only the sync writes it, and an object that is not synced does not carry it
    """
    PUBLIC_ID = 'public_id'
    TYPE_ID = 'type_id'
    ACTIVE = 'active'
    FIELDS = 'fields'
    MULTI_DATA_SECTIONS = 'multi_data_sections'
    CREATION_TIME = 'creation_time'
    LAST_EDIT_TIME = 'last_edit_time'
    AUTHOR_ID = 'author_id'
    VERSION = 'version'
    EDITOR_ID = 'editor_id'
    SPECIAL_TYPE = 'special_type'
    CI_EXPLORER_TOOLTIP = 'ci_explorer_tooltip'
    SYSTEM_REF = 'system_ref'


class CmdbObjectSystemRefKey(BaseStrEnum):
    """
    Dict keys of a CmdbObject's 'system_ref' - which user-management record the object mirrors

    KIND names the kind of record (``SystemRefKind``) and ID its public_id. Users and user groups have their own
    public_id sequences, which is why the id alone could not name the record
    """
    KIND = 'kind'
    ID = 'id'


class CmdbObjectSyncKey(BaseStrEnum):
    """
    Top-level keys the sync stores on a CmdbObject document that the model does not carry

    SYNC_HASH is the fingerprint of the values the sync wrote last, so a later pass writes only the objects whose
    user-management record changed. It is internal to the sync: never part of a response, a payload or an import
    """
    SYNC_HASH = 'sync_hash'


class CmdbObjectFieldKey(BaseStrEnum):
    """
    Dict keys of one entry inside a CmdbObject 'fields' list, or inside an MDS row's 'data' list

    Both contexts store the same shape ({'name': ..., 'value': ..., 'type': ...}), so the same
    enum applies to a top-level field entry and to a field entry nested inside a
    multi-data-section row. TYPE mirrors the FieldType of the field's definition on the
    CmdbType (e.g. 'text', 'select') and is mandatory on every stored entry
    """
    NAME = 'name'
    VALUE = 'value'
    TYPE = 'type'


class CmdbObjectMdsKey(BaseStrEnum):
    """
    Dict keys of one entry inside a CmdbObject 'multi_data_sections' list

    Each entry represents one MDS section instance on the object: SECTION_ID identifies the
    section template, HIGHEST_ID is the largest row id handed out so far (the row-id counter)
    and VALUES is the list of rows captured for that section
    """
    SECTION_ID = 'section_id'
    HIGHEST_ID = 'highest_id'
    VALUES = 'values'


class CmdbObjectMdsRowKey(BaseStrEnum):
    """
    Dict keys of one row inside a CmdbObject MDS section's 'values' list

    Each row stores its captured field entries under 'data' as a list of
    {name, value, type}-shaped dicts (see CmdbObjectFieldKey for that inner shape) and is
    identified within its section by MULTI_DATA_ID
    """
    MULTI_DATA_ID = 'multi_data_id'
    DATA = 'data'


# The keys holding a timestamp, read as CmdbObject's DATE_FIELDS: a payload carries the
# {'$date': ...} wrapper, and MongoDB can only sort and range-filter a real date
OBJECT_DATE_KEYS: tuple[CmdbObjectKey, ...] = (
    CmdbObjectKey.CREATION_TIME,
    CmdbObjectKey.LAST_EDIT_TIME,
)

# The keys only the sync writes: no object write, update or import takes them from a client, an update keeps the
# stored ones, and an imported object never brings its own
OBJECT_SYNC_KEYS: tuple[str, ...] = (
    CmdbObjectKey.SYSTEM_REF.value,
    CmdbObjectSyncKey.SYNC_HASH.value,
)
