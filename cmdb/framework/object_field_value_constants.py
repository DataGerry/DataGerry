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
Messages and pattern anchors of the CmdbObject field value rules

The rules themselves live in cmdb.framework.object_field_value_rules; the length caps they apply are
the CmdbType's (``cmdb.models.type_model.type_constants.FIELD_VALUE_MAX_LENGTHS``)
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The anchors the object form's pattern validator adds to a pattern that lacks them
PATTERN_START_ANCHOR: str = '^'
PATTERN_END_ANCHOR: str = '$'

# Appended to a message about a value inside a multi-data-section row
MDS_SECTION_SUFFIX: str = " in multi-data section '{section_id}'"

# Joins the messages of a Type or section-template write refused for its field defaults
FIELD_DEFAULT_ERROR_SEPARATOR: str = ' | '


class FieldValueError(BaseStrEnum):
    """
    Why a field value is refused

    Attributes:
        TOO_LONG: The value holds more characters than its field kind allows
        PATTERN_MISMATCH: The value does not match the pattern its field declares
    """
    TOO_LONG = "Value of field '{field}' is {length} characters long, at most {max_length} are allowed"
    PATTERN_MISMATCH = "Value of field '{field}' does not match the field's pattern '{regex}'"


class FieldDefaultError(BaseStrEnum):
    """
    Why a field's declared default value is refused

    The same two rules as FieldValueError, stated about the default a CmdbType or section-template field
    declares - the value every new object of it starts from

    Attributes:
        TOO_LONG: The default holds more characters than its field kind allows
        PATTERN_MISMATCH: The default does not match the pattern its own field declares
    """
    TOO_LONG = "Default value of field '{field}' is {length} characters long, at most {max_length} are allowed"
    PATTERN_MISMATCH = "Default value of field '{field}' does not match the field's pattern '{regex}'"
