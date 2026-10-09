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
Limits and refusal messages of a MediaFile write

Shared by the write schema (`media_file_schema`) and the REST routes that run it, so both sides spell
the same rule
"""
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MEDIA_FILE_NAME_MAX_LENGTH',
    'MEDIA_FILE_NAME_FORBIDDEN_CHARACTER',
    'FILENAME_NOT_A_STRING_MSG',
    'FILENAME_BLANK_MSG',
    'FILENAME_SEPARATOR_MSG',
    'FILENAME_TOO_LONG_MSG',
    'BOOLEAN_IS_NO_ID_MSG',
]

# A file's name is addressed in a URL path segment (`GET /media_file/<filename>`) and shown in the file
# explorer, so it may not contain the path separator; the cap matches the other user-named entities
MEDIA_FILE_NAME_MAX_LENGTH: int = 255
MEDIA_FILE_NAME_FORBIDDEN_CHARACTER: str = '/'

FILENAME_NOT_A_STRING_MSG: str = 'must be a string'
FILENAME_BLANK_MSG: str = 'must not be blank'
FILENAME_SEPARATOR_MSG: str = f"must not contain '{MEDIA_FILE_NAME_FORBIDDEN_CHARACTER}'"
FILENAME_TOO_LONG_MSG: str = f'must be at most {MEDIA_FILE_NAME_MAX_LENGTH} characters long'

# JSON true/false would pass as the integers 1/0, so an id field refuses a boolean explicitly
BOOLEAN_IS_NO_ID_MSG: str = 'must be an integer, not a boolean'
