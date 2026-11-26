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
Validation schema for CmdbAccessHistory

One entry of the access change history (collection ``access.history``): one changed access document - who, when, how,
before and after. Entries are written by the server only and never changed

This module is the single source of the document's Cerberus validation schema, consumed as CmdbAccessHistory.SCHEMA.
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #

def get_cmdb_access_history_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbAccessHistory document

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbAccessHistory.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running (see class_schema/__init__.py)
    from cmdb.models.access_model.access_history_constants import (
        MAX_HISTORY_COMMENT_LENGTH,
        AccessHistoryKey,
        HistoryAction,
        HistoryKind,
        HistorySource,
    )

    return {
        AccessHistoryKey.PUBLIC_ID.value: {'type': 'integer', 'min': 1},
        AccessHistoryKey.TIME.value: {'type': 'datetime', 'required': True},
        AccessHistoryKey.USER_ID.value: {'type': 'integer', 'nullable': True, 'required': True},
        AccessHistoryKey.USER_NAME.value: {'type': 'string', 'nullable': True, 'required': True},
        AccessHistoryKey.ACTION.value: {'type': 'string', 'required': True,
                                        'allowed': [action.value for action in HistoryAction]},
        AccessHistoryKey.KIND.value: {'type': 'string', 'required': True,
                                      'allowed': [kind.value for kind in HistoryKind]},
        AccessHistoryKey.DOCUMENT_ID.value: {'type': ['integer', 'string'], 'required': True},
        AccessHistoryKey.BEFORE.value: {'type': 'dict', 'nullable': True, 'required': True},
        AccessHistoryKey.AFTER.value: {'type': 'dict', 'nullable': True, 'required': True},
        AccessHistoryKey.CHANGED.value: {'type': 'list', 'schema': {'type': 'string'}, 'required': True},
        AccessHistoryKey.COMMENT.value: {'type': 'string', 'nullable': True,
                                         'maxlength': MAX_HISTORY_COMMENT_LENGTH},
        AccessHistoryKey.GROUP_IDS.value: {'type': 'list', 'schema': {'type': 'integer'}, 'required': True},
        AccessHistoryKey.SOURCE.value: {'type': 'string', 'required': True,
                                        'allowed': [source.value for source in HistorySource]},
    }
