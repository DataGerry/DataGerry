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
Constants of the port text rules (``port_text_rules``)

The cap itself is not here: it is ``TEXT_VALUE_MAX_LENGTH``, the one every CmdbType text field, every
cable text field and the port document schema use, so the port surface cannot drift from them
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# How much of an over-long generated name a refusal quotes - enough to recognise it, never the whole thing
NAME_EXCERPT_LENGTH: int = 40

# Appended to a quoted excerpt that was cut
EXCERPT_ELLIPSIS: str = '...'


class PortTextError(BaseStrEnum):
    """
    Messages reported when a port text value is refused

    Members with a `{...}` placeholder are filled via `format()`. Every one is a business-rule rejection
    surfaced as an HTTP 400
    """
    NOT_TEXT = "'{field}' must be text, but was {value_type}!"
    TOO_LONG = "'{field}' is {length} characters long - at most {maximum} are allowed!"
    NAMES_TOO_LONG = (
        "{count} of the generated port names are longer than {maximum} characters - the first: '{excerpt}' "
        "({length} characters). Shorten the syntax, the prefix or the slot, or start the numbering lower!"
    )


# Prefix of the aggregated 400 the port routes build from the reasons above
TEXT_ABORT_PREFIX: str = 'Port text validation failed'
