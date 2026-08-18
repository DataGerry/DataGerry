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
All constants for rendering in DataGerry
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

ANONYMOUS_NAME = 'unknown'


class RenderedFieldKey(BaseStrEnum):
    """
    Enumeration of the expansion keys a renderer ADDS to a field entry

    A rendered field starts out as the field definition of a CmdbType (whose keys are covered by
    `FieldKey`) and is then enriched by `CmdbMultiRender` with the resolved data behind a reference.
    Those extra keys live only on the render output — never on the stored type or object document —
    which is why they are not part of `FieldKey` / `CmdbObjectKey`. Use these members instead of bare
    string literals when reading a rendered field so a typo becomes an AttributeError instead of a
    silently missing expansion
    """
    #: Set on a `FieldType.REFERENCE` field; holds the referenced object's expansion
    REFERENCE = 'reference'
    #: List of the referenced object's summary fields, inside `REFERENCE`
    SUMMARIES = 'summaries'
    #: Set on a `FieldType.REF_SECTION` field; holds the pulled-in section's expansion
    REFERENCES = 'references'
    #: List of the pulled-in fields, inside `REFERENCES`
    FIELDS = 'fields'
