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
Shared constants for CmdbTypes

Names the ACL rights guarding the CmdbType REST routes so the routes and any other consumer
stay aligned on the literal strings instead of repeating them. Mirrors the SectionTemplateRight
convention in ``section_template_constants``.

Also holds DG_LOCATION_FIELD_NAME, the reserved name of the one location field a CmdbType may
declare - the renderer, the CI Explorer, DocAPI and both importers all identify it by that name,
DEFAULT_PORT_SECTION_INDEX / MIN_PORT_SECTION_INDEX, the position the ports section falls back to and
the lowest one it may be given, and NestedSummaryKey, the keyset of a nested-summary entry.
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# Reserved name of the location field. A CmdbType has at most one field of type FieldType.LOCATION
# and it always carries this name; every consumer that resolves a location value looks it up by it
DG_LOCATION_FIELD_NAME: str = 'dg_location'

# Where the ports section sits when a CmdbType says nothing about it: first, above every declared
# section. Also the value forced onto a type that does not use ports, so the key is never a stale
# position left over from a type that once did
DEFAULT_PORT_SECTION_INDEX: int = 0

# The lowest position the ports section may be given. Same number as the default, but a different
# statement: 0 is where an unspecified index lands, and it is also the first slot that exists
MIN_PORT_SECTION_INDEX: int = 0


class TypeRight(BaseStrEnum):
    """
    ACL right identifiers guarding the CmdbType REST routes
    """
    ADD = 'base.framework.type.add'
    VIEW = 'base.framework.type.view'
    EDIT = 'base.framework.type.edit'
    DELETE = 'base.framework.type.delete'


class NestedSummaryKey(BaseStrEnum):
    """
    Keys of one entry in a reference field's ``summaries`` list

    A `FieldType.REFERENCE` field may override, per referenced CmdbType, which summary fields and
    which summary line the renderer shows for it. Each override is one entry in the field
    definition's ``summaries`` list, addressed by the referenced type's public_id

    Attributes:
        TYPE_ID: public_id of the referenced CmdbType this entry applies to
        FIELDS: Names of the fields to summarise for that type
        LINE: Summary-line template to render for that type
        PREFIX: Whether the referenced type's label prefixes the rendered summary line
    """
    TYPE_ID = 'type_id'
    FIELDS = 'fields'
    LINE = 'line'
    PREFIX = 'prefix'
