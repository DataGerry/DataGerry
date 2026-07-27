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
Shared constants for the CmdbType import REST routes
"""
from cmdb.utils import BaseStrEnum
from cmdb.models.type_model import TypeSchemaKey
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'UNKNOWN_TYPE_ERROR_KEY_TEMPLATE',
    'IMPORT_UPDATE_PRESERVED_FIELDS',
    'TypeImporterFormField',
    'TypeImportError',
]

# Fields an import UPDATE must never write. They describe how the type came to exist on THIS system,
# so the uploaded values (which belong to the system the type was exported from) are dropped from the
# update payload; because the update is a `$set`, omitting a field leaves the stored value untouched
IMPORT_UPDATE_PRESERVED_FIELDS: tuple[str, ...] = (
    TypeSchemaKey.AUTHOR_ID.value,
    TypeSchemaKey.CREATION_TIME.value,
)

# Error-collection key used for an uploaded entry that carries no usable public_id, so a failure can
# still be reported back to the caller instead of raising while building the report
UNKNOWN_TYPE_ERROR_KEY_TEMPLATE: str = 'entry_{index}'


class TypeImporterFormField(BaseStrEnum):
    """Multipart form-field names read from a type-import request"""
    UPLOAD_FILE = 'uploadFile'


class TypeImportError(BaseStrEnum):
    """
    Messages reported for a type import

    NO_UPLOAD_FILE and INVALID_UPLOAD_PAYLOAD are raised as an HTTP 400 for the whole request; every
    other member is a per-entry message recorded in the error collection and carries a `{...}`
    placeholder filled via `format()`
    """
    NO_UPLOAD_FILE = 'No upload file was provided!'
    INVALID_UPLOAD_PAYLOAD = 'The uploaded data must be a JSON list of Types!'
    SPECIAL_TYPE_NOT_LICENSED = 'The IPAM feature is not licensed, so the special Type "{special_type}" ' \
                                'can not be imported!'
    PUBLIC_ID_ASSIGNMENT_FAILED = 'Failed to assign a public_id to this Type: {detail}'
    INVALID_TYPE_DATA = 'Failed to create a Type instance from the provided data: {detail}'
    IMPORT_FAILED = 'Failed to import this Type: {detail}'
    TYPE_NOT_FOUND = 'No Type with public_id {public_id} exists, it can not be updated!'
    UPDATE_FAILED = 'Failed to update this Type: {detail}'
