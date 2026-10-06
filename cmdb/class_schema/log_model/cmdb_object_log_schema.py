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
Validation schema for CmdbObjectLog

A CmdbObjectLog records a create / edit / activation change / delete made to a CmdbObject
(collection ``framework.logs``).

This module is the single source of the document's Cerberus validation schema,
consumed as CmdbObjectLog.SCHEMA.

It describes the entry the object write paths store, and nothing validates against it at write time - an
entry is written best-effort after the object write, and refusing it would lose the change record. It is
kept honest by a test instead: every entry shape the writer produces must validate. What that entry is:

* ``LogsManager.insert_log`` sets ``public_id``, ``action`` / ``action_name`` (a ``LogAction``), ``log_type``
  and ``log_time``; ``build_object_log_data`` adds ``object_id``, ``user_id``, ``version`` (the object's
  version string, e.g. ``'1.0.1'``), ``user_name`` (the user's DISPLAY name - ``'First Last'`` or the user
  name, an e-mail address in cloud mode), ``comment``, ``render_state`` (the rendered object as
  JSON-encoded bytes) and ``type_id`` (the rendered object's CmdbType - what the log reads are judged by;
  null on an entry whose type could not be determined)
* ``changes`` depends on the action: the field diff ``{'old': [...], 'new': [...]}`` on EDIT,
  ``{'old': bool, 'new': bool}`` on ACTIVE_CHANGE, and ``[]`` on CREATE and DELETE, which record none
"""
from typing import Any
# -------------------------------------------------------------------------------------------------------------------- #
# pylint: disable=R0801
def get_cmdb_object_log_schema() -> dict[str, Any]:
    """
    Builds the Cerberus validation schema for a CmdbObjectLog document

    A required field carries no ``default``: Cerberus applies a default BEFORE the required check, so a
    default would both disable ``required`` and fill a missing value in

    Returns:
        dict[str, Any]: Field name to Cerberus rule mapping, consumed as CmdbObjectLog.SCHEMA
    """
    # pylint: disable=import-outside-toplevel
    # Resolved at call time, not at module import time: the model imports this builder while its own
    # package __init__ is still running, so a module-level import back into cmdb.models would close that
    # cycle and leave every class_schema module unimportable on its own (see class_schema/__init__.py)
    from cmdb.models.log_model.log_action_enum import LogAction
    from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE

    return {
        'public_id': {  # public_id of the log entry itself
            'type': 'integer',
            'required': True,
        },
        'object_id': {  # public_id of the CmdbObject this log entry refers to
            'type': 'integer',
            'required': True,
        },
        'version': {  # The object's version at log time, e.g. '1.0.1'
            'type': 'string',
            'nullable': True,
            'required': True,
        },
        'user_id': {  # public_id of the CmdbUser who triggered the action
            'type': 'integer',
            'required': True,
        },
        'user_name': {  # The acting user's display name: 'First Last', or the user name (an e-mail in cloud)
            'type': 'string',
            'required': True,
        },
        'render_state': {  # The object as rendered at log time, JSON-encoded bytes (BSON binary)
            'type': 'binary',
            'nullable': True,
            'required': True,
        },
        'type_id': {  # public_id of the logged object's CmdbType at log time; null when it could not be determined
            'type': 'integer',
            'nullable': True,
        },
        'log_type': {  # Log type discriminator - always CmdbObjectLog for this document
            'type': 'string',
            'allowed': [OBJECT_LOG_TYPE],
            'required': True,
        },
        'log_time': {  # When the entry was written (UTC)
            'type': 'datetime',
            'required': True,
        },
        'changes': {  # EDIT: the field diff; ACTIVE_CHANGE: {'old': bool, 'new': bool}; CREATE / DELETE: []
            'type': ['dict', 'list'],
            'default': [],
        },
        'comment': {  # The comment the write path records (an ObjectLogComment, or the user's edit comment)
            'type': 'string',
            'nullable': True,
        },
        'action': {  # The LogAction value
            'type': 'integer',
            'allowed': [action.value for action in LogAction],
            'required': True,
        },
        'action_name': {  # The LogAction name
            'type': 'string',
            'allowed': [action.name for action in LogAction],
            'required': True,
        },
    }
