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
the one that matches where in the structure the key lives. All four extend BaseStrEnum so
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
    the top-level field list and the multi-data-section list
    """
    PUBLIC_ID = 'public_id'
    TYPE_ID = 'type_id'
    FIELDS = 'fields'
    MULTI_DATA_SECTIONS = 'multi_data_sections'


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
    section template and VALUES is the list of rows captured for that section
    """
    SECTION_ID = 'section_id'
    VALUES = 'values'


class CmdbObjectMdsRowKey(BaseStrEnum):
    """
    Dict keys of one row inside a CmdbObject MDS section's 'values' list

    Each row stores its captured field entries under 'data' as a list of
    {name, value, type}-shaped dicts (see CmdbObjectFieldKey for that inner shape)
    """
    DATA = 'data'
