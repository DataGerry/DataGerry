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
Enumeration of the keys of a rendered reference expansion
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

class TypeReferenceKey(BaseStrEnum):
    """
    Enumeration of the keys `TypeReference.to_json` emits

    This is the payload `CmdbMultiRender` writes under a reference field's `reference` key, and it is
    read by three parties: the Angular reference field (which shows LINE when one is set, otherwise
    ICON + TYPE_LABEL + `#`OBJECT_ID + SUMMARIES, and hides the whole block while OBJECT_ID is 0), the
    human-readable exporter (which builds its own line from TYPE_LABEL, OBJECT_ID and SUMMARIES), and
    the search-result matcher (which looks for hits inside SUMMARIES).

    Owned by the model layer because `TypeReference` produces the payload; before 2026-09-10 every
    consumer described the same seven keys with literals or constants of its own. Use these members
    instead of bare string literals so a typo becomes an AttributeError instead of a silently missing
    key in a rendered object
    """
    #: public_id of the referenced object's CmdbType (0 on the empty reference)
    TYPE_ID = 'type_id'
    #: public_id of the referenced CmdbObject - 0 marks the EMPTY reference the frontend hides
    OBJECT_ID = 'object_id'
    #: The referenced object's summary line, placeholders already filled. Empty when the type
    #: configures none, or when filling it failed
    LINE = 'line'
    #: Label of the referenced object's CmdbType
    TYPE_LABEL = 'type_label'
    #: The referenced object's summary FIELDS (name / value / type entries), shown when LINE is empty
    SUMMARIES = 'summaries'
    #: Icon class of the referenced object's CmdbType
    ICON = 'icon'
    #: Whether the type's summary configuration asks for the label to be prefixed
    PREFIX = 'prefix'
