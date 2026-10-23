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
The request and response contract of the configuration transfer routes, and their refusal messages
"""
from typing import Any

from cmdb.utils import BaseStrEnum
from cmdb.models.group_model import MASTER_RIGHT_NAME
from cmdb.framework.configuration_transfer.best_practice_meta_schema import NON_BLANK_PATTERN
from cmdb.framework.configuration_transfer.configuration_transfer_constants import (
    INFORMATION_DESCRIPTION_MAX_LENGTH,
    INFORMATION_NAME_MAX_LENGTH,
)
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'CONFIGURATION_EXPORT_RIGHT',
    'CONFIGURATION_TRANSFER_RIGHT',
    'CONFIGURATION_EXPORT_MIMETYPE',
    'CONFIGURATION_EXPORT_FILE_EXTENSION',
    'CONFIGURATION_EXPORT_JSON_INDENT',
    'EXPORT_FILENAME_INPUT_MAX_LENGTH',
    'ExportRequestKey',
    'EXPORT_REQUEST_SCHEMA',
    'NO_DB_VERSION_MESSAGE',
    'EXPORT_FAILED_MESSAGE',
    'IMPORT_UPLOAD_FIELD',
    'ImportResponseKey',
    'PreviewResponseKey',
    'PREVIEW_FAILED_MESSAGE',
    'NO_IMPORT_FILE_MESSAGE',
    'IMPORT_FILE_NOT_JSON_MESSAGE',
    'NOT_RESET_MESSAGE',
    'IMPORT_PROBLEMS_MESSAGE',
    'IMPORT_FAILED_MESSAGE',
    'IMPORT_UNDO_INCOMPLETE_MESSAGE',
    'RESET_CONFIRMATION',
    'ResetRequestKey',
    'ResetResponseKey',
    'RESET_REQUEST_SCHEMA',
    'RESET_FAILED_MESSAGE',
]

# The right exporting the configuration asks for - a SystemRight the admin group holds through base.*
CONFIGURATION_EXPORT_RIGHT: str = 'base.system.export'
# The right the import, the reset and applying a best-practice model ask for: the master right itself, held by the
# admin group - they replace the whole configuration, so no narrower right can grant them
CONFIGURATION_TRANSFER_RIGHT: str = MASTER_RIGHT_NAME

CONFIGURATION_EXPORT_MIMETYPE: str = 'application/json'
CONFIGURATION_EXPORT_FILE_EXTENSION: str = 'json'
# Indented so an export can be read and two exports diffed, like the type export
CONFIGURATION_EXPORT_JSON_INDENT: int = 2

# The longest filename the export body may ask for - the stem is capped further when it is cleaned
EXPORT_FILENAME_INPUT_MAX_LENGTH: int = 255


class ExportRequestKey(BaseStrEnum):
    """Keys of the `POST /configuration_transfer/export` body"""
    # What the user calls the export - written to the file's `information`
    NAME = 'name'
    # The user's description of it - written to the file's `information`, empty when none is given
    DESCRIPTION = 'description'
    # The download's filename - the generated one when none is given or nothing usable is left of it
    FILENAME = 'filename'


EXPORT_REQUEST_SCHEMA: dict[str, Any] = {
    ExportRequestKey.NAME.value: {
        'type': 'string',
        'required': True,
        'empty': False,
        'regex': NON_BLANK_PATTERN,
        'maxlength': INFORMATION_NAME_MAX_LENGTH,
    },
    ExportRequestKey.DESCRIPTION.value: {
        'type': 'string',
        'maxlength': INFORMATION_DESCRIPTION_MAX_LENGTH,
        'default': '',
    },
    ExportRequestKey.FILENAME.value: {
        'type': 'string',
        'nullable': True,
        'maxlength': EXPORT_FILENAME_INPUT_MAX_LENGTH,
        'default': None,
    },
}

# The multipart field the import's transfer file is uploaded in
IMPORT_UPLOAD_FIELD: str = 'file'


class PreviewResponseKey(BaseStrEnum):
    """Keys of the `POST /configuration_transfer/import/preview` answer"""
    # The file's `information` as it is - None when it has none or it has a problem of its own
    INFORMATION = 'information'
    # The collections that still hold data the import would collide with - empty on a reset system
    RESET_BLOCKERS = 'reset_blockers'
    # Every problem the import would name for the file - empty when it may be imported
    PROBLEMS = 'problems'
    # Whether the import would run: no reset blockers and no problems
    IMPORTABLE = 'importable'


class ImportResponseKey(BaseStrEnum):
    """Keys of the `POST /configuration_transfer/import` answer"""
    # The number of documents imported per component, in import order
    IMPORTED = 'imported'


# The value the reset body must carry - what the admin types into the frontend's confirmation field
RESET_CONFIRMATION: str = 'RESET'


class ResetRequestKey(BaseStrEnum):
    """Keys of the `POST /configuration_transfer/reset` body"""
    CONFIRM = 'confirm'


class ResetResponseKey(BaseStrEnum):
    """Keys of the `POST /configuration_transfer/reset` answer"""
    # The number of documents deleted per collection, in the order the reset cleared them
    DELETED = 'deleted'


RESET_REQUEST_SCHEMA: dict[str, Any] = {
    ResetRequestKey.CONFIRM.value: {
        'type': 'string',
        'required': True,
        'allowed': [RESET_CONFIRMATION],
    },
}

RESET_FAILED_MESSAGE: str = "while resetting the configuration - run the reset again to finish it"
NO_DB_VERSION_MESSAGE: str = (
    "The database records no valid version, so no importable export can be produced - start DataGerry once to "
    "let its updater record one"
)
EXPORT_FAILED_MESSAGE: str = "while exporting the configuration"
NO_IMPORT_FILE_MESSAGE: str = "No transfer file was uploaded - send it as the multipart field 'file'"
IMPORT_FILE_NOT_JSON_MESSAGE: str = "The transfer file is not valid UTF-8 JSON: {detail}"
NOT_RESET_MESSAGE: str = (
    "The system is not reset - these collections still hold data the import would collide with: {collections}. "
    "Reset the configuration first"
)
IMPORT_PROBLEMS_MESSAGE: str = "The transfer file cannot be imported: {problems}"
IMPORT_FAILED_MESSAGE: str = "while importing the configuration - nothing was imported"
PREVIEW_FAILED_MESSAGE: str = "while previewing the configuration import - nothing was imported"
IMPORT_UNDO_INCOMPLETE_MESSAGE: str = (
    "The configuration import failed and could not be completely undone. Still in effect: {residue}"
)
