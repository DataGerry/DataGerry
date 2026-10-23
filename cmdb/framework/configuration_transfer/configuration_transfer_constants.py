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
The keys, component names and problem messages of a configuration transfer file

A transfer file is one JSON document:

    {
        "format_version": 1,
        "db_version": 20261014,
        "exported_at": "2026-10-12T09:30:00+00:00",
        "information": {"name": "...", "description": "...", "version": "3.4.0", "counts": {"types": 40, ...}},
        "meta": {"title": "", ..., "order": null},
        "components": {
            "section_templates": {"counter": 12, "items": [...]},
            "types": {"counter": 40, "items": [...]},
            ...
        }
    }

`format_version` versions the envelope itself, `db_version` is the updater version of the database the file was
exported from - an import only accepts a file whose `db_version` equals its own, because the documents carry the
shape that version stores. `information` is what the exporting user says about the file (name, description) plus
what the export fills in (the DataGerry release and the number of entries per component). `meta` is what the start
assistant shows about a best-practice model (``BestPracticeMetaKey``): an export writes it with empty values, and it is
filled in by hand only for a file that becomes a best-practice model
"""
from typing import Any

from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

# The envelope version this code writes and the only one it reads
TRANSFER_FORMAT_VERSION: int = 1


class TransferFileKey(BaseStrEnum):
    """The top-level keys of a transfer file"""
    FORMAT_VERSION = 'format_version'
    DB_VERSION = 'db_version'
    EXPORTED_AT = 'exported_at'
    INFORMATION = 'information'
    META = 'meta'
    COMPONENTS = 'components'


class TransferInformationKey(BaseStrEnum):
    """The keys of a transfer file's `information` section"""
    # What the exporting user calls the file
    NAME = 'name'
    # The exporting user's description of it - empty when none was given
    DESCRIPTION = 'description'
    # The DataGerry release that wrote the file
    VERSION = 'version'
    # The number of entries per component, keyed by the component's name
    COUNTS = 'counts'


# The longest an `information` name and description may be
INFORMATION_NAME_MAX_LENGTH: int = 255
INFORMATION_DESCRIPTION_MAX_LENGTH: int = 4000


class TransferSectionKey(BaseStrEnum):
    """The keys of one component's section in a transfer file"""
    # The component's public_id counter at export time
    COUNTER = 'counter'
    # The component's documents, each with its public_id
    ITEMS = 'items'


class TransferComponentName(BaseStrEnum):
    """The components a transfer file carries, each the key of its section"""
    SECTION_TEMPLATES = 'section_templates'
    TYPES = 'types'
    CATEGORIES = 'categories'
    RELATIONS = 'relations'


# Matches every document not flagged predefined - an absent flag counts as not predefined
NOT_PREDEFINED: dict[str, Any] = {'$ne': True}

# -------------------------------------------------------------------------------------------------------------------- #
#                                                   PROBLEM MESSAGES                                                   #
# -------------------------------------------------------------------------------------------------------------------- #

FILE_NOT_AN_OBJECT: str = "The transfer file must be a JSON object"
MISSING_FILE_KEY: str = "The transfer file has no '{key}'"
UNKNOWN_FILE_KEY: str = "The transfer file has an unknown key '{key}'"
FORMAT_VERSION_MISMATCH: str = "The transfer file's '{key}' must be {expected}"
DB_VERSION_NOT_A_NUMBER: str = "The transfer file's '{key}' must be a positive whole number"
EXPORTED_AT_NOT_A_STRING: str = "The transfer file's '{key}' must be a non-blank string"
FILE_KEY_NOT_AN_OBJECT: str = "The transfer file's '{key}' must be a JSON object"
MISSING_COMPONENT: str = "The transfer file has no '{name}' component"
UNKNOWN_COMPONENT: str = "The transfer file has an unknown component '{name}'"
SECTION_NOT_AN_OBJECT: str = "The '{name}' component must be a JSON object"
MISSING_SECTION_KEY: str = "The '{name}' component has no '{key}'"
UNKNOWN_SECTION_KEY: str = "The '{name}' component has an unknown key '{key}'"
COUNTER_NOT_A_NUMBER: str = "The '{name}' component's '{key}' must be a whole number of 0 or more"
ITEMS_NOT_A_LIST: str = "The '{name}' component's '{key}' must be a list"
ITEM_NOT_AN_OBJECT: str = "Entry {index} of the '{name}' component must be a JSON object"
MISSING_SECTION_FIELD: str = "The transfer file's '{section}' has no '{key}'"
UNKNOWN_SECTION_FIELD: str = "The transfer file's '{section}' has an unknown key '{key}'"
INFORMATION_NOT_TEXT: str = "The transfer file's '{section}' '{key}' must be a non-blank string"
INFORMATION_NOT_A_STRING: str = "The transfer file's '{section}' '{key}' must be a string"
INFORMATION_TOO_LONG: str = "The transfer file's '{section}' '{key}' may be at most {max_length} characters long"
MISSING_COUNT: str = "The transfer file's '{section}' counts have no '{key}' component"
UNKNOWN_COUNT: str = "The transfer file's '{section}' counts have an unknown component '{key}'"
COUNT_NOT_A_NUMBER: str = "The transfer file's '{section}' count of '{name}' must be a whole number of 0 or more"
COUNT_MISMATCH: str = (
    "The transfer file's '{section}' counts {count} '{name}' entries, but the component holds {actual}"
)
META_INVALID: str = "The transfer file's '{key}' is invalid: {errors}"
DB_VERSION_MISMATCH: str = (
    "The transfer file was exported from database version {file_version}, this system is at version "
    "{target_version} - only a file of the same version can be imported"
)

# -------------------------------------------------------------------------------------------------------------------- #
#                                               COMPONENT ORDER PROBLEMS                                               #
# -------------------------------------------------------------------------------------------------------------------- #

DUPLICATE_COMPONENT: str = "The component '{name}' is registered more than once"
DEPENDENCY_NOT_BEFORE: str = "The component '{name}' depends on '{dependency}', which is not registered before it"

# -------------------------------------------------------------------------------------------------------------------- #
#                                                        RESET                                                         #
# -------------------------------------------------------------------------------------------------------------------- #

# How many GridFS files one delete round takes - bounds the size of the `$in` list a round sends
RESET_DELETE_BATCH_SIZE: int = 1000

# -------------------------------------------------------------------------------------------------------------------- #
#                                                        IMPORT                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

# What the import's undoable writes are called when an undo cannot finish one
COUNTER_RESTORED: str = "the public_id counter of '{collection}' set to {value}"
PREDEFINED_TEMPLATES_REMOVED: str = "the predefined section templates removed for re-seeding"
USER_SETTINGS_CLEARED: str = "every user's settings cleared"

# Passed as a read's projection to get whole documents, `_id` included - the database layer drops `_id` otherwise
WHOLE_DOCUMENT: None = None

# -------------------------------------------------------------------------------------------------------------------- #
#                                                       STAGING                                                        #
# -------------------------------------------------------------------------------------------------------------------- #

# A file from an older version is migrated in a temporary database named this, followed by 32 hex characters - the
# prefix says what the database is, should one ever be left behind
STAGING_DATABASE_PREFIX: str = 'tmp_test_configuration_import_'
# How often a fresh name is drawn when the drawn one exists already, before the import gives up
MAX_STAGING_NAME_ATTEMPTS: int = 5

DB_VERSION_TOO_NEW: str = (
    "The transfer file was exported from database version {file_version}, which is newer than this system's "
    "{target_version} - a file can only be imported into the same or a newer version"
)
NO_STAGING_NAME: str = "No unused name for the temporary migration database was found in {attempts} attempts"
