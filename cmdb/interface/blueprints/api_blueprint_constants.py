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
Named values of the APIBlueprint request decorators

The texts and limits of the 400 a schema-validated route answers when its body is refused
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Leads every refusal, so a client can tell a schema rejection from a route's own 400
INVALID_BODY_MESSAGE: str = 'Invalid data provided'

# Answered when the validator itself fails. It names nothing: the schema is internal, and the
# exception is logged with its traceback instead
VALIDATION_FAILED_MESSAGE: str = 'The request body could not be validated'

# At most this many field errors are spelled out; a body refused for hundreds of list items would
# otherwise produce a message of the same size
MAX_REPORTED_SCHEMA_ERRORS: int = 5

# How one field's path and its reason are joined, and how the reported errors are joined to each other
FIELD_ERROR_SEPARATOR: str = ': '
ERRORS_SEPARATOR: str = '; '
