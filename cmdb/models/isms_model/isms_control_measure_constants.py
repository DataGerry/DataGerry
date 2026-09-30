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
Document keys of an IsmsControlMeasure

The keys of the ``isms.controlMeasure`` documents, named once. The model's ``from_data`` and
``to_json``, the Cerberus schema, and both halves of the CSV importer (its header set and the candidate
row it builds) all read them from here, so a renamed or mistyped key fails as an error instead of
showing up as a silently missing value.

Members are the raw MongoDB keys; use ``.value`` wherever a key is needed as a dict key, a Mongo
filter key or a projection key, so what reaches the database is a plain string
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CONTROL_MEASURE_REQUIRED_DOCUMENT_KEYS',
    'ControlMeasureKey',
    'CONTROL_MEASURE_IMPORT_KEYS',
]


class ControlMeasureKey(BaseStrEnum):
    """
    Field keys of an IsmsControlMeasure document
    """
    PUBLIC_ID = 'public_id'
    TITLE = 'title'
    CONTROL_MEASURE_TYPE = 'control_measure_type'
    SOURCE = 'source'
    IMPLEMENTATION_STATE = 'implementation_state'
    IDENTIFIER = 'identifier'
    CHAPTER = 'chapter'
    DESCRIPTION = 'description'
    IS_APPLICABLE = 'is_applicable'
    REASON = 'reason'


# The columns a control-measure CSV carries: every document key except the server-owned public_id.
# Derived rather than repeated, so the importer's header contract cannot drift from the document
CONTROL_MEASURE_IMPORT_KEYS: tuple[str, ...] = tuple(
    key.value for key in ControlMeasureKey if key is not ControlMeasureKey.PUBLIC_ID
)


# Every key the schema requires except 'is_applicable', whose absence means False (see the model)
CONTROL_MEASURE_REQUIRED_DOCUMENT_KEYS: list[str] = [
    key.value for key in ControlMeasureKey
    if key not in (ControlMeasureKey.PUBLIC_ID, ControlMeasureKey.IS_APPLICABLE)
]
