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
Integration tests for the object-log read rule against a real MongoDB

A log is read through the type ACL of the object it records, by the ``type_id`` stamped on it. Two implementations
decide it: the lists hand the caller's READ ACL to ``LogsManager.iterate`` (the ACL stage matches ``type_id`` ahead
of the paging), and a single read asks ``logs_helper.is_log_readable``. Pinned for every stamp a log can carry -
an ACL'd type granting or denying the group, a type without an ACL, a deactivated ACL, a type that no longer
exists, null and a missing key:

  - both implementations agree, log by log
  - the list leaves a hidden log out of the page AND the total, so paging a restricted user's history is correct
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import LogsManager, TypesManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.models.log_model.cmdb_meta_log import CmdbMetaLog
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import is_log_readable
# -------------------------------------------------------------------------------------------------------------------- #

GROUP_ID: int = 1
OTHER_GROUP_ID: int = 2
LOGGED_OBJECT_ID: int = 98000

GRANTING_TYPE_ID: int = 98001
DENYING_TYPE_ID: int = 98002
OPEN_TYPE_ID: int = 98003
DEACTIVATED_TYPE_ID: int = 98004
GONE_TYPE_ID: int = 98009

# (log public_id, the stamp - a type id, None, or MISSING for no key - and whether GROUP_ID may read it)
MISSING: object = object()
LOG_MATRIX: list[tuple[int, Any, bool]] = [
    (98011, GRANTING_TYPE_ID, True),
    (98012, DENYING_TYPE_ID, False),
    (98013, OPEN_TYPE_ID, True),
    (98014, DEACTIVATED_TYPE_ID, True),
    (98015, GONE_TYPE_ID, True),
    (98016, None, True),
    (98017, MISSING, True),
    (98018, DENYING_TYPE_ID, False),
]
ALL_LOG_IDS: list[int] = [public_id for public_id, _stamp, _readable in LOG_MATRIX]
READABLE_LOG_IDS: list[int] = [public_id for public_id, _stamp, readable in LOG_MATRIX if readable]

TYPE_DOCUMENTS: list[dict[str, Any]] = [
    {'public_id': GRANTING_TYPE_ID, 'name': 'log-acl-granting',
     'acl': {'activated': True, 'groups': {'includes': {str(GROUP_ID): ['READ']}}}},
    {'public_id': DENYING_TYPE_ID, 'name': 'log-acl-denying',
     'acl': {'activated': True, 'groups': {'includes': {str(OTHER_GROUP_ID): ['READ']}}}},
    {'public_id': OPEN_TYPE_ID, 'name': 'log-acl-open'},
    {'public_id': DEACTIVATED_TYPE_ID, 'name': 'log-acl-deactivated',
     'acl': {'activated': False, 'groups': {'includes': {str(OTHER_GROUP_ID): ['READ']}}}},
]
ALL_TYPE_IDS: list[int] = [document['public_id'] for document in TYPE_DOCUMENTS]


READER: CmdbUser = CmdbUser(public_id=1, user_name='log-acl-reader', active=True, group_id=GROUP_ID)


@pytest.fixture(autouse=True)
def _app_context(rest_api):
    """The REST app's context: the ACL stage reaches the types through ManagerProvider"""
    with rest_api.application.app_context():
        yield


def _log(public_id: int, stamp: Any) -> dict[str, Any]:
    """A stored object log with the given stamp"""
    document: dict[str, Any] = {
        'public_id': public_id, 'log_type': OBJECT_LOG_TYPE, 'object_id': LOGGED_OBJECT_ID, 'action': 1,
        'action_name': 'EDIT', 'version': '1.0.1', 'user_id': 1, 'user_name': 'admin', 'changes': [],
        'render_state': b'{}',
    }

    if stamp is not MISSING:
        document['type_id'] = stamp

    return document


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The ACL'd types and one log per stamp, purged before and after"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    logs = database_manager.get_collection(CmdbMetaLog.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': ALL_TYPE_IDS + [GONE_TYPE_ID]}})
        logs.delete_many({'public_id': {'$in': ALL_LOG_IDS}})

    _purge()
    types.insert_many([dict(document) for document in TYPE_DOCUMENTS])
    logs.insert_many([_log(public_id, stamp) for public_id, stamp, _readable in LOG_MATRIX])
    yield logs
    _purge()


def _listed(database_manager: MongoDatabaseManager, limit: int = 0, skip: int = 0) -> tuple[list[int], int]:
    """The seeded logs as a list route reads them for GROUP_ID: the page's ids and the total"""
    logs_manager = LogsManager(database_manager)
    params = BuilderParameters({'object_id': LOGGED_OBJECT_ID}, limit=limit, skip=skip, sort='public_id', order=1)

    result = logs_manager.iterate(params, READER, AccessControlPermission.READ)

    return [log.public_id for log in result.results], result.total


@pytest.mark.parametrize('public_id, readable', [(row[0], row[2]) for row in LOG_MATRIX],
                         ids=[str(row[0]) for row in LOG_MATRIX])
def test_both_implementations_agree(
    seeded, database_manager: MongoDatabaseManager, public_id: int, readable: bool,
) -> None:
    """The single-log decision and the list's ACL stage, asked about the same stored log"""
    stored: dict[str, Any] = seeded.find_one({'public_id': public_id})
    listed_ids, _total = _listed(database_manager)

    single: bool = is_log_readable(stored, READER, TypesManager(database_manager))

    assert single is readable
    assert (public_id in listed_ids) is readable


def test_the_list_leaves_hidden_logs_out_of_the_total(database_manager: MongoDatabaseManager) -> None:
    """The total counts what the caller may read - the pager is built from it"""
    listed_ids, total = _listed(database_manager)

    assert listed_ids == READABLE_LOG_IDS
    assert total == len(READABLE_LOG_IDS)


def test_paging_runs_over_the_readable_logs(database_manager: MongoDatabaseManager) -> None:
    """The ACL stage runs before $skip / $limit, so the second page is the next readable logs"""
    second_page, _total = _listed(database_manager, limit=2, skip=2)

    assert second_page == READABLE_LOG_IDS[2:4]
