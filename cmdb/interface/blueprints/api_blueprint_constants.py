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

The texts and limits of the 400 a schema-validated route answers when its body is refused, and the
names and texts of the right check `protect` runs
"""
# -------------------------------------------------------------------------------------------------------------------- #

# Leads every refusal, so a client can tell a schema rejection from a route's own 400
INVALID_BODY_MESSAGE: str = 'Invalid data provided'

# Answered when the request body is not a JSON object - no body at all, or a list, a string or a number - so the
# schema of a write route has nothing to check
BODY_NOT_AN_OBJECT_MESSAGE: str = 'The request body must be a JSON object'

# Answered when the validator itself fails. It names nothing: the schema is internal, and the
# exception is logged with its traceback instead
VALIDATION_FAILED_MESSAGE: str = 'The request body could not be validated'

# At most this many field errors are spelled out; a body refused for hundreds of list items would
# otherwise produce a message of the same size
MAX_REPORTED_SCHEMA_ERRORS: int = 5

# How one field's path and its reason are joined, and how the reported errors are joined to each other
FIELD_ERROR_SEPARATOR: str = ': '
ERRORS_SEPARATOR: str = '; '

# The keyword argument `insert_request_user` injects the authenticated CmdbUser under, which `protect` checks
REQUEST_USER_KWARG: str = 'request_user'

# A route whose `protect` has no `insert_request_user` above it: a wiring fault, not the caller's
PROTECT_WITHOUT_REQUEST_USER_MESSAGE: str = 'The route could not identify the request user!'

# The user's group could not be read, so the right could not be checked - distinct from a missing right
RIGHT_CHECK_FAILED_MESSAGE: str = 'The rights of the request user could not be checked!'
