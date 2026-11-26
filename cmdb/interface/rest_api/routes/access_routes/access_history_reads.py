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
The reads and the one setting of the access change history: the list's filters, the export (JSON or CSV, on the long
time budget, newest first) and the retention - a TTL index kept in step with the setting, the change itself recorded
"""
import json
from collections.abc import Iterator
from typing import Any

from flask import abort, request

from cmdb.manager import AccessHistoryManager, SettingsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.database.database_constants import LONG_QUERY_TIME_LIMIT_MS
from cmdb.models.access_model import (
    HISTORY_SETTINGS_SECTION,
    AccessHistoryKey,
    HistoryAction,
    HistoryKind,
    HistorySettingsKey,
)
from cmdb.models.user_model import CmdbUser
from cmdb.utils import BaseStrEnum, Builder
from cmdb.framework.access_rules.access_history import csv_lines
from cmdb.interface.route_utils import abort_if_query_too_slow
from cmdb.interface.rest_api.routes.routes_helper import read_id_query_param, undone_on_failure
from cmdb.interface.rest_api.routes.access_routes.access_history_helper import ChangeContext, record_change
from cmdb.errors.manager import BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

__all__: list[str] = [
    'HistoryQuery',
    'HistoryExportFormat',
    'EXPORT_LIMIT',
    'NEWEST_FIRST',
    'history_condition',
    'export_entries',
    'export_body',
    'retention_days',
    'set_retention',
]

# The most entries one export answers, newest first
EXPORT_LIMIT: int = 100000
NEWEST_FIRST: int = -1
UNKNOWN_KIND_MESSAGE: str = "'{kind}' is no kind of the access history - one of {kinds}!"
SETTINGS_UNDO_INCOMPLETE_MESSAGE: str = "Changing the history retention failed and could not be undone: {residue}"
_SETTINGS_ID: str = '_id'
_MONGO_ID: str = '_id'


class HistoryQuery(BaseStrEnum):
    """The history list's and export's own query parameters"""
    GROUP_ID = 'group_id'
    KIND = 'kind'
    DOCUMENT_ID = 'document_id'
    FORMAT = 'format'


class HistoryExportFormat(BaseStrEnum):
    """What an export answers"""
    JSON = 'json'
    CSV = 'csv'


def history_condition() -> dict[str, Any]:
    """
    The server-side condition of ``?group_id=``, ``?kind=`` and ``?document_id=``

    Raises:
        HTTPException: 400 for a group id that is no id, an unknown kind

    Returns:
        dict[str, Any]: The condition; empty without the parameters
    """
    condition: dict[str, Any] = {}
    group_id: int | None = read_id_query_param(HistoryQuery.GROUP_ID.value)
    kind: str | None = request.args.get(HistoryQuery.KIND.value)
    document_id: str | None = request.args.get(HistoryQuery.DOCUMENT_ID.value)

    if group_id is not None:
        condition[AccessHistoryKey.GROUP_IDS.value] = group_id

    if kind is not None:
        if kind not in {member.value for member in HistoryKind}:
            abort(400, UNKNOWN_KIND_MESSAGE.format(kind=kind, kinds=sorted(member.value for member in HistoryKind)))

        condition[AccessHistoryKey.KIND.value] = kind

    if document_id is not None:
        condition[AccessHistoryKey.DOCUMENT_ID.value] = int(document_id) if document_id.isdigit() else document_id

    return condition


def export_entries(request_user: CmdbUser, condition: dict[str, Any]) -> list[dict[str, Any]]:
    """
    The entries an export answers, newest first, at most ``EXPORT_LIMIT``

    Args:
        request_user (CmdbUser): The caller - names the tenant
        condition (dict[str, Any]): The filter (``history_condition``)

    Raises:
        HTTPException: 503 when the read ran past its time budget
        AccessHistoryManagerIterationError: When the read fails

    Returns:
        list[dict[str, Any]]: The entries as stored, without the database id
    """
    history: AccessHistoryManager = ManagerProvider.get_manager(ManagerType.ACCESS_HISTORY, request_user)
    pipeline: list[dict[str, Any]] = [
        Builder.match_(condition),
        Builder.sort_({AccessHistoryKey.TIME.value: NEWEST_FIRST, AccessHistoryKey.PUBLIC_ID.value: NEWEST_FIRST}),
        Builder.limit_(EXPORT_LIMIT),
        Builder.project_({_MONGO_ID: 0}),
    ]

    try:
        return history.aggregate_within_time_limit(pipeline, LONG_QUERY_TIME_LIMIT_MS)
    except BaseManagerIterationError as err:
        abort_if_query_too_slow(err)
        raise


def export_body(entries: list[dict[str, Any]], export_format: str) -> tuple[Iterator[str] | str, str]:
    """
    An export's body and media type

    Args:
        entries (list[dict[str, Any]]): The entries
        export_format (str): ``json`` or ``csv``

    Returns:
        tuple[Iterator[str] | str, str]: The body (CSV line by line) and its media type
    """
    if export_format == HistoryExportFormat.CSV.value:
        return csv_lines(entries), 'text/csv'

    return json.dumps(entries, default=str), 'application/json'


def retention_days(request_user: CmdbUser) -> int:
    """
    How many days the history keeps an entry - 0 for ever

    Args:
        request_user (CmdbUser): The caller - names the tenant

    Returns:
        int: The days
    """
    settings: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    days: Any = settings.get_value(HistorySettingsKey.RETENTION_DAYS.value, HISTORY_SETTINGS_SECTION)

    return days if isinstance(days, int) and not isinstance(days, bool) and days > 0 else 0


def set_retention(request_user: CmdbUser, days: int, comment: str | None) -> int:
    """
    Changes the retention: the setting, the TTL index and the change's history entry - all or nothing

    Args:
        request_user (CmdbUser): The caller
        days (int): The new retention; 0 keeps every entry
        comment (str | None): The caller's comment

    Raises:
        AccessHistoryManagerUpdateError: When the index could not be changed (the setting is put back)
        AccessHistoryManagerInsertError: When the entry could not be written (setting and index put back)

    Returns:
        int: The retention as stored
    """
    settings: SettingsManager = ManagerProvider.get_manager(ManagerType.SETTINGS, request_user)
    history: AccessHistoryManager = ManagerProvider.get_manager(ManagerType.ACCESS_HISTORY, request_user)
    prior: int = retention_days(request_user)

    def write(value: int) -> None:
        settings.write(HISTORY_SETTINGS_SECTION, {_SETTINGS_ID: HISTORY_SETTINGS_SECTION,
                                                  HistorySettingsKey.RETENTION_DAYS.value: value})
        history.apply_retention(value)

    with undone_on_failure(SETTINGS_UNDO_INCOMPLETE_MESSAGE) as ledger:
        ledger.compensated(SettingsManager.COLLECTION, HISTORY_SETTINGS_SECTION, lambda: write(prior),
                           lambda: retention_days(request_user) == prior)
        write(days)
        record_change(ChangeContext(request_user, HistoryKind.HISTORY_SETTINGS, comment), HistoryAction.UPDATE,
                      HISTORY_SETTINGS_SECTION, {HistorySettingsKey.RETENTION_DAYS.value: prior},
                      {HistorySettingsKey.RETENTION_DAYS.value: days}, [], ledger)

    return days
