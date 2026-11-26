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
The constants of the access change history: an entry's keys, what changed, how and through what
"""
from cmdb.utils import BaseStrEnum
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'AccessHistoryKey',
    'HistoryAction',
    'HistoryKind',
    'HistorySource',
    'MAX_HISTORY_COMMENT_LENGTH',
    'HISTORY_TTL_INDEX_NAME',
    'HISTORY_COMMENT_KEY',
    'HISTORY_SETTINGS_SECTION',
    'MAX_RETENTION_DAYS',
    'HistorySettingsKey',
]

# The longest comment a write may leave on its entries
MAX_HISTORY_COMMENT_LENGTH: int = 1000
# The body key / query parameter a write's comment travels in - never stored on the document
HISTORY_COMMENT_KEY: str = 'comment'
# The settings section of the history, and the longest retention it may be given (about a century)
HISTORY_SETTINGS_SECTION: str = 'access_history'
MAX_RETENTION_DAYS: int = 36500
# The name of the index the retention expires entries by
HISTORY_TTL_INDEX_NAME: str = 'time_ttl'


class AccessHistoryKey(BaseStrEnum):
    """
    Keys of one entry of the access change history - one changed document

    Attributes:
        PUBLIC_ID: The entry's public_id
        TIME: When the change was written (UTC)
        USER_ID / USER_NAME: Who made it - the name as it was then
        ACTION: ``HistoryAction``
        KIND: ``HistoryKind`` - what kind of document changed
        DOCUMENT_ID: The changed document's public_id; for a field ``<source>:<source id>:<field name>``
        BEFORE / AFTER: The document before and after - None for a create / a delete
        CHANGED: The top-level keys whose value differs, ascending
        COMMENT: The writer's comment, or None
        GROUP_IDS: The user groups the change concerns, when it was written
        SOURCE: ``HistorySource`` - a route, or the cascade that made it
    """
    PUBLIC_ID = 'public_id'
    TIME = 'time'
    USER_ID = 'user_id'
    USER_NAME = 'user_name'
    ACTION = 'action'
    KIND = 'kind'
    DOCUMENT_ID = 'document_id'
    BEFORE = 'before'
    AFTER = 'after'
    CHANGED = 'changed'
    COMMENT = 'comment'
    GROUP_IDS = 'group_ids'
    SOURCE = 'source'


class HistoryAction(BaseStrEnum):
    """How the document changed"""
    CREATE = 'create'
    UPDATE = 'update'
    DELETE = 'delete'


class HistoryKind(BaseStrEnum):
    """What kind of access document changed - the only ones the history records"""
    FIELD_CLASS = 'field_class'
    SCOPE_ROLE = 'scope_role'
    ASSIGNMENT = 'assignment'
    FIELD_RULE = 'field_rule'
    FIELD_PROTECTION = 'field_protection'
    HISTORY_SETTINGS = 'history_settings'


class HistorySource(BaseStrEnum):
    """What made the change: an access route, or a cascade of another write"""
    ROUTE = 'route'
    GROUP_DELETE = 'group_delete'
    TYPE_DELETE = 'type_delete'
    CONFIGURATION_RESET = 'configuration_reset'


class HistorySettingsKey(BaseStrEnum):
    """The keys of the history's settings"""
    RETENTION_DAYS = 'retention_days'
