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
Write schemas of a MediaFile: its metadata sub-document and the body of an update

The upload arrives as a multipart form, so its metadata is a JSON form field rather than the request body
the `validate` decorator reads; both write routes therefore run these schemas themselves. The metadata
schema is the one both paths share: every key of `MediaFileMetadataKey` is optional, a declared key holds
a value of its declared type, and no other key is allowed. The update body is the whole MediaFile as the
file explorer sends it, so keys beyond the three it is made of are tolerated and ignored
"""
from typing import Any, Callable

from cmdb.framework.media_library.media_file_keys import MediaFileKey, MediaFileMetadataKey
from cmdb.framework.media_library.media_library_constants import (
    MEDIA_FILE_NAME_MAX_LENGTH,
    MEDIA_FILE_NAME_FORBIDDEN_CHARACTER,
    FILENAME_NOT_A_STRING_MSG,
    FILENAME_BLANK_MSG,
    FILENAME_SEPARATOR_MSG,
    FILENAME_TOO_LONG_MSG,
    BOOLEAN_IS_NO_ID_MSG,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'MEDIA_FILE_METADATA_SCHEMA',
    'MEDIA_FILE_UPDATE_SCHEMA',
    'filename_problem',
]


def filename_problem(name: Any) -> str | None:
    """
    Names what makes a MediaFile name unusable, if anything

    A name is a non-blank string of at most `MEDIA_FILE_NAME_MAX_LENGTH` characters without the path
    separator - the single read route addresses a file by its name as one URL path segment

    Args:
        name (Any): The name as it arrived

    Returns:
        str | None: The reason the name is refused, or None for a usable name
    """
    if not isinstance(name, str):
        return FILENAME_NOT_A_STRING_MSG

    if not name.strip():
        return FILENAME_BLANK_MSG

    if MEDIA_FILE_NAME_FORBIDDEN_CHARACTER in name:
        return FILENAME_SEPARATOR_MSG

    if len(name) > MEDIA_FILE_NAME_MAX_LENGTH:
        return FILENAME_TOO_LONG_MSG

    return None


def _check_filename(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Cerberus `check_with` rule applying `filename_problem`

    Args:
        field (str): The field being validated
        value (Any): Its value
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    problem = filename_problem(value)

    if problem:
        error(field, problem)


def _check_no_boolean(field: str, value: Any, error: Callable[[str, str], None]) -> None:
    """
    Cerberus `check_with` rule refusing a boolean where an id (or a list of ids) belongs

    Python counts `True` / `False` as the integers 1 / 0, so the `integer` type alone lets them through

    Args:
        field (str): The field being validated
        value (Any): Its value - an id, or a list of ids
        error (Callable[[str, str], None]): Cerberus' error reporter
    """
    values: list[Any] = value if isinstance(value, list) else [value]

    if any(isinstance(item, bool) for item in values):
        error(field, BOOLEAN_IS_NO_ID_MSG)


def _id_rule(nullable: bool = True) -> dict[str, Any]:
    """
    The rule of a field holding one public_id

    Args:
        nullable (bool): Whether the field may be null

    Returns:
        dict[str, Any]: The Cerberus rule
    """
    return {'type': 'integer', 'nullable': nullable, 'check_with': _check_no_boolean}


# Every key optional; a reference is one id (the attachment upload) or a list of them (an attachment added
# or removed through the update); `permission` is reserved and holds anything
MEDIA_FILE_METADATA_SCHEMA: dict[str, Any] = {
    MediaFileMetadataKey.REFERENCE.value: {
        'type': ['integer', 'list'],
        'nullable': True,
        'schema': {'type': 'integer'},
        'check_with': _check_no_boolean,
    },
    MediaFileMetadataKey.REFERENCE_TYPE.value: {'type': 'string', 'nullable': True},
    MediaFileMetadataKey.MIME_TYPE.value: {'type': 'string', 'nullable': True},
    MediaFileMetadataKey.AUTHOR_ID.value: _id_rule(),
    MediaFileMetadataKey.FOLDER.value: {'type': 'boolean'},
    MediaFileMetadataKey.PARENT.value: _id_rule(),
    MediaFileMetadataKey.PERMISSION.value: {'nullable': True},
}

# The update body: the stored file's identity, its (new) name and its whole metadata
MEDIA_FILE_UPDATE_SCHEMA: dict[str, Any] = {
    MediaFileKey.PUBLIC_ID.value: {**_id_rule(nullable=False), 'required': True},
    MediaFileKey.FILENAME.value: {'required': True, 'check_with': _check_filename},
    MediaFileKey.METADATA.value: {
        'required': True,
        'type': 'dict',
        'allow_unknown': False,
        'schema': MEDIA_FILE_METADATA_SCHEMA,
    },
}
