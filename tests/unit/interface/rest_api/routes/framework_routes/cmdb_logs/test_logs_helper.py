# DATAGERRY - OpenSource Enterprise CMDB
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
Unit tests for the CmdbLog route helpers

Pure tests: no Mongo and no Flask app.

* ``build_object_logs_response``: the logs manager, BuilderParameters, GetMultiResponse and
  CmdbObjectLog.to_json are patched, so only the helper's own wiring is exercised - that it builds
  the BuilderParameters from the query + pagination, serializes every iterated row, forwards the
  total/url/HEAD flag to GetMultiResponse, and returns its ``make_response`` output.
* the existence split: the deleted-object pipeline's shape, the cap on the ids read, the filter each side
  builds from them and the per-log join it falls back to. Whether MongoDB splits the logs the way the shapes
  promise is the integration and functional suites' job.
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database.database_constants import QUERY_TIME_LIMIT_MS
from cmdb.errors.manager import BaseManagerIterationError
from cmdb.models.object_model import CmdbObject
from cmdb.security.acl.permission import AccessControlPermission
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.object_log_constants import OBJECT_LOG_TYPE
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_constants import (
    LOG_ACCESS_DENIED_MSG,
    LogKey,
    LogQueryOperator,
    MAX_DELETED_OBJECT_IDS,
    MONGO_ID_KEY,
    OBJECT_LOOKUP_FIELD,
    OBJECT_LOOKUP_FIRST_MATCH,
    OBJECT_LOOKUP_MAX_MATCHES,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper import (
    abort_unless_log_readable,
    build_deleted_object_ids_pipeline,
    build_object_log_existence_filter,
    build_object_log_existence_join,
    build_object_log_existence_query,
    build_object_logs_response,
    is_log_readable,
    object_entry_actions,
    read_deleted_object_ids,
    resolve_log_users,
    serialize_object_log,
)
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
# -------------------------------------------------------------------------------------------------------------------- #

HELPER_PATH: str = 'cmdb.interface.rest_api.routes.framework_routes.cmdb_logs.logs_helper'

QUERY: dict[str, Any] = {'object_id': 42}
REQUEST_URL: str = 'http://localhost/rest/logs/object/42'
TOTAL_LOGS: int = 2


def _params() -> MagicMock:
    """A CollectionParameters stand-in with the four fields the helper reads."""
    params = MagicMock()
    params.limit = 10
    params.skip = 0
    params.sort = 'public_id'
    params.order = 1
    return params


def _request(method: str = 'GET') -> MagicMock:
    """A Flask request stand-in exposing url + method; include_users defaults off."""
    request = MagicMock()
    request.url = REQUEST_URL
    request.method = method
    request.args.get.return_value = 'false'
    return request


def _manager_returning(rows: list[Any]) -> MagicMock:
    """A LogsManager mock whose ``iterate`` yields the given rows and a fixed total."""
    manager = MagicMock()
    iteration_result = MagicMock()
    iteration_result.results = rows
    iteration_result.total = TOTAL_LOGS
    manager.iterate.return_value = iteration_result
    return manager


def test_builds_params_serializes_rows_and_wraps_response() -> None:
    """The helper threads query+pagination into BuilderParameters, reads through the caller's READ ACL and
    serializes each iterated row."""
    rows = [object(), object()]
    manager = _manager_returning(rows)
    params = _params()
    request = _request('GET')
    request_user = MagicMock()

    with patch(f'{HELPER_PATH}.BuilderParameters') as builder_cls, \
         patch(f'{HELPER_PATH}.CmdbObjectLog.to_json', side_effect=lambda row: {'row': id(row)}) as to_json_mock, \
         patch(f'{HELPER_PATH}.GetMultiResponse') as response_cls:
        result = build_object_logs_response(manager, QUERY, params, request, request_user)

    builder_cls.assert_called_once_with(QUERY, params.limit, params.skip, params.sort, params.order)
    manager.iterate.assert_called_once_with(builder_cls.return_value, request_user, AccessControlPermission.READ)
    assert to_json_mock.call_count == len(rows)

    serialized = [{'row': id(rows[0])}, {'row': id(rows[1])}]
    response_cls.assert_called_once_with(serialized, TOTAL_LOGS, params, REQUEST_URL, True)
    assert result is response_cls.return_value.make_response.return_value


@pytest.mark.parametrize('method,expected_body', [('GET', True), ('HEAD', False)])
def test_the_body_flag_reflects_the_request_method(method: str, expected_body: bool) -> None:
    """
    The GetMultiResponse body flag is True for everything BUT a HEAD request

    Asserted the other way round it would read: this helper derives the flag as
    `request.method == HTTP_HEAD_METHOD`, so a plain GET asked for a bodyless answer - harmless only
    which an inert flag would hide. The rule comes from
    `routes_helper.request_wants_body`.
    """
    manager = _manager_returning([])
    params = _params()
    request = _request(method)

    with patch(f'{HELPER_PATH}.BuilderParameters'), \
         patch(f'{HELPER_PATH}.CmdbObjectLog.to_json'), \
         patch(f'{HELPER_PATH}.GetMultiResponse') as response_cls:
        build_object_logs_response(manager, QUERY, params, request, MagicMock())

    _, _, _, _, body_flag = response_cls.call_args.args
    assert body_flag is expected_body


class TestResolveLogUsers:
    """resolve_log_users dedupes user_ids, keys by stringified public_id, and omits missing users."""

    def test_dedupes_ids_and_keys_by_public_id(self) -> None:
        """Distinct user_ids are queried once; the map is keyed by the stringified public_id."""
        manager = MagicMock()
        manager.get_minimal_users_by_ids.return_value = [
            {'public_id': 1, 'first_name': 'Ada', 'last_name': 'Lovelace', 'image': None, 'user_name': 'ada'},
            {'public_id': 2, 'first_name': '', 'last_name': '', 'image': None, 'user_name': 'grace'},
        ]
        logs = [{'user_id': 1}, {'user_id': 2}, {'user_id': 1}]

        result = resolve_log_users(manager, logs)

        assert set(manager.get_minimal_users_by_ids.call_args.args[0]) == {1, 2}
        assert set(result) == {'1', '2'}
        assert result['1']['user_name'] == 'ada'

    def test_omits_missing_users_and_skips_null_ids(self) -> None:
        """A user_id with no matching user is omitted; None/absent user_ids are not queried."""
        manager = MagicMock()
        manager.get_minimal_users_by_ids.return_value = [
            {'public_id': 1, 'first_name': 'Ada', 'last_name': 'Lovelace', 'image': None, 'user_name': 'ada'},
        ]
        logs = [{'user_id': 1}, {'user_id': 2}, {'user_id': None}, {}]

        result = resolve_log_users(manager, logs)

        assert set(manager.get_minimal_users_by_ids.call_args.args[0]) == {1, 2}
        assert set(result) == {'1'}

    def test_no_user_ids_returns_empty_without_query(self) -> None:
        """With no resolvable user_ids the manager is not queried and an empty map is returned."""
        manager = MagicMock()

        result = resolve_log_users(manager, [{'user_id': None}, {}])

        assert result == {}
        manager.get_minimal_users_by_ids.assert_not_called()


# -------------------------------------------------------------------------------------------------------------------- #
#                                      the existence split (exists / notexists)                                        #
# -------------------------------------------------------------------------------------------------------------------- #
DELETED_OBJECT_IDS: list[Any] = [11, 23, None]
# The actions of an object's own history, spelled out: the helper derives them from LogAction, the test states them
OBJECT_ENTRY_ACTIONS: list[int] = [LogAction.CREATE.value, LogAction.EDIT.value, LogAction.ACTIVE_CHANGE.value]
OBJECT_LOG_ENTRY_CONDITION: dict[str, Any] = {
    LogKey.LOG_TYPE.value: OBJECT_LOG_TYPE,
    LogKey.ACTION.value: {LogQueryOperator.IN.value: OBJECT_ENTRY_ACTIONS},
}
OBJECT_PROBE: list[dict[str, Any]] = [
    {'$limit': OBJECT_LOOKUP_MAX_MATCHES},
    {'$project': {MONGO_ID_KEY: 1}},
]


def _logs_manager_answering(rows: list[dict[str, Any]]) -> MagicMock:
    """A LogsManager stand-in whose aggregation answers the given rows"""
    logs_manager = MagicMock()
    logs_manager.aggregate_within_time_limit.return_value = rows
    return logs_manager


def _rows(count: int) -> list[dict[str, Any]]:
    """`count` deleted-object rows with distinct ids"""
    return [{MONGO_ID_KEY: object_id} for object_id in range(count)]


def _lookup(pipeline: list[dict[str, Any]]) -> dict[str, Any]:
    """The body of the pipeline's one `$lookup` stage"""
    lookups = [stage['$lookup'] for stage in pipeline if '$lookup' in stage]
    assert len(lookups) == 1
    return lookups[0]


class TestDeletedObjectIdsPipeline:
    """`build_deleted_object_ids_pipeline`: one join per object, read off the index"""

    def test_the_stages_run_group_join_split_trim_cap(self) -> None:
        """Grouping first is what makes it one join per object instead of one per log"""
        operators = [next(iter(stage)) for stage in build_deleted_object_ids_pipeline()]

        assert operators == ['$group', '$lookup', '$match', '$project', '$limit']

    def test_it_groups_every_log_by_object_id_without_a_filter(self) -> None:
        """No `$match` ahead of the `$group`: unfiltered, MongoDB reads it off the object_id index alone"""
        first_stage = build_deleted_object_ids_pipeline()[0]

        assert first_stage == {'$group': {MONGO_ID_KEY: f'${LogKey.OBJECT_ID.value}'}}

    def test_the_join_matches_the_grouped_id_to_an_objects_public_id(self) -> None:
        """After the `$group` the object id is `_id`; the object carries it as `public_id`"""
        lookup = _lookup(build_deleted_object_ids_pipeline())

        assert lookup['from'] == CmdbObject.COLLECTION
        assert lookup['localField'] == MONGO_ID_KEY
        assert lookup['foreignField'] == LogKey.PUBLIC_ID.value
        assert lookup['as'] == OBJECT_LOOKUP_FIELD
        assert lookup['pipeline'] == OBJECT_PROBE

    def test_it_keeps_the_ids_no_object_carries(self) -> None:
        """Element 0 of the joined array is missing exactly when the object is"""
        split_stage = build_deleted_object_ids_pipeline()[2]

        assert split_stage == {'$match': {OBJECT_LOOKUP_FIRST_MATCH: {LogQueryOperator.EXISTS.value: False}}}

    def test_each_row_is_the_id_alone(self) -> None:
        """The joined array is dropped; the caller reads `_id` only"""
        assert build_deleted_object_ids_pipeline()[3] == {'$project': {MONGO_ID_KEY: 1}}

    def test_it_reads_one_row_past_the_cap(self) -> None:
        """One row more than the cap is what tells a cut list from one that is exactly at the cap"""
        assert build_deleted_object_ids_pipeline()[-1] == {'$limit': MAX_DELETED_OBJECT_IDS + 1}


class TestReadDeletedObjectIds:
    """`read_deleted_object_ids`: the ids, or None when they are too many to send as a list"""

    def test_answers_the_ids_in_row_order(self) -> None:
        """Each row's `_id` is one deleted object id; a missing object_id comes back as None"""
        logs_manager = _logs_manager_answering([{MONGO_ID_KEY: object_id} for object_id in DELETED_OBJECT_IDS])

        assert read_deleted_object_ids(logs_manager) == DELETED_OBJECT_IDS

    def test_runs_the_pipeline_under_the_page_time_budget(self) -> None:
        """A read that outgrows the budget answers like a slow page does"""
        logs_manager = _logs_manager_answering([])

        read_deleted_object_ids(logs_manager)

        logs_manager.aggregate_within_time_limit.assert_called_once_with(
            build_deleted_object_ids_pipeline(), QUERY_TIME_LIMIT_MS,
        )

    def test_no_deleted_object_is_an_empty_list_not_none(self) -> None:
        """An empty list is a usable answer; None would send the caller down the join"""
        assert read_deleted_object_ids(_logs_manager_answering([])) == []

    def test_exactly_the_cap_is_still_a_list(self) -> None:
        """The cap itself fits"""
        assert len(read_deleted_object_ids(_logs_manager_answering(_rows(MAX_DELETED_OBJECT_IDS)))) \
            == MAX_DELETED_OBJECT_IDS

    def test_one_past_the_cap_is_none(self) -> None:
        """The extra row the pipeline reads means the list was cut"""
        assert read_deleted_object_ids(_logs_manager_answering(_rows(MAX_DELETED_OBJECT_IDS + 1))) is None

    def test_a_failed_read_propagates(self) -> None:
        """The routes map it (400, or 503 on the time budget); swallowing it would answer a wrong split"""
        logs_manager = MagicMock()
        logs_manager.aggregate_within_time_limit.side_effect = BaseManagerIterationError('boom')

        with pytest.raises(BaseManagerIterationError):
            read_deleted_object_ids(logs_manager)


class TestObjectLogExistenceFilter:
    """`build_object_log_existence_filter`: one side of the split as a plain filter"""

    def test_exists_excludes_the_deleted_ids(self) -> None:
        """The "exists" side is every object log whose object id is not a deleted one"""
        assert build_object_log_existence_filter(DELETED_OBJECT_IDS, True) == {
            **OBJECT_LOG_ENTRY_CONDITION,
            LogKey.OBJECT_ID.value: {LogQueryOperator.NIN.value: DELETED_OBJECT_IDS},
        }

    def test_notexists_selects_the_deleted_ids(self) -> None:
        """The "notexists" side is every object log whose object id is a deleted one"""
        assert build_object_log_existence_filter(DELETED_OBJECT_IDS, False) == {
            **OBJECT_LOG_ENTRY_CONDITION,
            LogKey.OBJECT_ID.value: {LogQueryOperator.IN.value: DELETED_OBJECT_IDS},
        }

    def test_it_is_a_filter_not_a_pipeline(self) -> None:
        """A filter is what keeps the page and the count free of any join"""
        assert isinstance(build_object_log_existence_filter(DELETED_OBJECT_IDS, True), dict)


class TestObjectLogExistenceJoin:
    """`build_object_log_existence_join`: the per-log fallback"""

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_only_object_logs_that_are_not_deletes_enter(self, object_exists: bool) -> None:
        """A delete log has no object by construction; letting it in would fill /notexists with them"""
        assert build_object_log_existence_join(object_exists)[0] == {'$match': OBJECT_LOG_ENTRY_CONDITION}

    def test_the_join_matches_the_logs_object_by_public_id(self) -> None:
        """A log names its object by `object_id`; the object carries that value as `public_id`"""
        lookup = _lookup(build_object_log_existence_join(True))

        assert lookup['from'] == CmdbObject.COLLECTION
        assert lookup['localField'] == LogKey.OBJECT_ID.value
        assert lookup['foreignField'] == LogKey.PUBLIC_ID.value
        assert lookup['as'] == OBJECT_LOOKUP_FIELD
        assert lookup['pipeline'] == OBJECT_PROBE

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_the_split_reads_the_first_joined_element(self, object_exists: bool) -> None:
        """The last stage decides the side: element 0 of the joined array is there exactly when the object is"""
        last_stage = build_object_log_existence_join(object_exists)[-1]

        assert last_stage == {'$match': {OBJECT_LOOKUP_FIRST_MATCH: {LogQueryOperator.EXISTS.value: object_exists}}}

    def test_the_stages_run_filter_join_split(self) -> None:
        """Filtering first keeps the per-log join off the delete logs; no `$unwind` is needed for the split"""
        operators = [next(iter(stage)) for stage in build_object_log_existence_join(True)]

        assert operators == ['$match', '$lookup', '$match']

    def test_the_first_joined_element_path_names_the_join_field(self) -> None:
        """The split path and the join target must name the same field, or every log lands on one side"""
        assert OBJECT_LOOKUP_FIRST_MATCH == f'{OBJECT_LOOKUP_FIELD}.0'


class TestObjectLogExistenceQuery:
    """`build_object_log_existence_query`: the filter when the ids fit, the join when they do not"""

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_the_filter_when_the_deleted_ids_fit(self, object_exists: bool) -> None:
        """The ids read once become the filter of the page"""
        logs_manager = _logs_manager_answering([{MONGO_ID_KEY: object_id} for object_id in DELETED_OBJECT_IDS])

        assert build_object_log_existence_query(logs_manager, object_exists) \
            == build_object_log_existence_filter(DELETED_OBJECT_IDS, object_exists)

    @pytest.mark.parametrize('object_exists', [True, False], ids=['exists', 'notexists'])
    def test_the_join_when_the_deleted_ids_do_not_fit(self, object_exists: bool) -> None:
        """Past the cap the list would not fit one command; the join answers the same rows at any size"""
        logs_manager = _logs_manager_answering(_rows(MAX_DELETED_OBJECT_IDS + 1))

        assert build_object_log_existence_query(logs_manager, object_exists) \
            == build_object_log_existence_join(object_exists)

    def test_the_default_selects_existing_objects(self) -> None:
        """`/logs/object/exists` passes no side"""
        logs_manager = _logs_manager_answering([{MONGO_ID_KEY: object_id} for object_id in DELETED_OBJECT_IDS])

        assert build_object_log_existence_query(logs_manager) == build_object_log_existence_filter(
            DELETED_OBJECT_IDS, True,
        )

    def test_the_deleted_ids_are_read_once(self) -> None:
        """One aggregation per request; the page and its count share its answer"""
        logs_manager = _logs_manager_answering([])

        build_object_log_existence_query(logs_manager)

        logs_manager.aggregate_within_time_limit.assert_called_once()


# -------------------------------------------------------------------------------------------------------------------- #
#                                          is_log_readable / the 403 helpers                                           #
# -------------------------------------------------------------------------------------------------------------------- #
LOG_ID: int = 900
LOGGED_TYPE_ID: int = 7
LOGGED_OBJECT_ID: int = 42
READER_GROUP_ID: int = 5
OTHER_GROUP_ID: int = 6


def _type_granting(group_id: int) -> dict[str, Any]:
    """A stored type whose activated ACL grants READ to one group"""
    return {'public_id': LOGGED_TYPE_ID, 'acl': {'activated': True, 'groups': {'includes': {str(group_id): ['READ']}}}}


def _types_manager(stored_type: dict[str, Any] | None) -> MagicMock:
    """A TypesManager stand-in answering one stored type (or none)"""
    types_manager = MagicMock()
    types_manager.get_type.return_value = stored_type
    return types_manager


def _reader(group_id: int = READER_GROUP_ID) -> MagicMock:
    """A caller of one group"""
    user = MagicMock()
    user.group_id = group_id
    return user


def _log(type_id: Any = LOGGED_TYPE_ID) -> dict[str, Any]:
    """A stored log stamped with a type (or without the key when None is not meant as a value)"""
    return {LogKey.PUBLIC_ID.value: LOG_ID, LogKey.TYPE_ID.value: type_id}


class TestIsLogReadable:
    """The single-log decision the list ACL stage makes, on the log's stamped type"""

    def test_a_type_granting_the_caller_reads(self) -> None:
        """The caller's group is in the type's READ list"""
        assert is_log_readable(_log(), _reader(), _types_manager(_type_granting(READER_GROUP_ID))) is True

    def test_a_type_denying_the_caller_hides_the_log(self) -> None:
        """An activated ACL naming another group"""
        assert is_log_readable(_log(), _reader(), _types_manager(_type_granting(OTHER_GROUP_ID))) is False

    def test_the_stamped_type_is_the_one_read(self) -> None:
        """Not the object's - the log's own type_id"""
        types_manager = _types_manager(_type_granting(READER_GROUP_ID))

        is_log_readable(_log(), _reader(), types_manager)

        types_manager.get_type.assert_called_once_with(LOGGED_TYPE_ID)

    def test_a_log_without_a_type_is_readable_without_a_read(self) -> None:
        """An entry the backfill could not attribute - the ACL stage lets it through too"""
        types_manager = _types_manager(_type_granting(OTHER_GROUP_ID))

        assert is_log_readable(_log(None), _reader(), types_manager) is True
        types_manager.get_type.assert_not_called()

    def test_a_log_whose_type_is_gone_is_readable(self) -> None:
        """A deleted type denies nobody"""
        assert is_log_readable(_log(), _reader(), _types_manager(None)) is True

    def test_a_type_without_an_activated_acl_reads(self) -> None:
        """Access control is opt-in"""
        assert is_log_readable(_log(), _reader(), _types_manager({'public_id': LOGGED_TYPE_ID})) is True


class TestAbortUnlessLogReadable:
    """The 403 of a single read, /corresponding and the delete"""

    def test_a_hidden_log_is_a_403_naming_it(self) -> None:
        """The message names the log, not the object"""
        with pytest.raises(HTTPException) as exc_info:
            abort_unless_log_readable(_log(), _reader(), _types_manager(_type_granting(OTHER_GROUP_ID)))

        assert exc_info.value.code == 403
        assert exc_info.value.description == LOG_ACCESS_DENIED_MSG.format(public_id=LOG_ID)

    def test_a_readable_log_passes(self) -> None:
        """No exception"""
        abort_unless_log_readable(_log(), _reader(), _types_manager(_type_granting(READER_GROUP_ID)))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 serialize_object_log                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
COMPLETE_LOG: dict[str, Any] = {
    'public_id': LOG_ID, 'log_type': OBJECT_LOG_TYPE, 'object_id': LOGGED_OBJECT_ID, 'type_id': LOGGED_TYPE_ID,
    'action': 1, 'action_name': 'EDIT', 'version': '1.0.1', 'user_id': 1, 'user_name': 'admin', 'comment': 'c',
    'changes': {'old': [], 'new': []}, 'render_state': b'{}', 'log_time': None,
}


class TestSerializeObjectLog:
    """One shape for a log, whether a list bound it or a single read loaded the document"""

    def test_a_stored_document_reads_like_the_bound_log(self) -> None:
        """The single read and the list row of the same log are equal"""
        assert serialize_object_log(dict(COMPLETE_LOG)) == serialize_object_log(CmdbObjectLog.from_data(COMPLETE_LOG))

    def test_a_complete_document_keeps_every_value(self) -> None:
        """Nothing stored is changed on the way out"""
        assert serialize_object_log(dict(COMPLETE_LOG)) == COMPLETE_LOG

    def test_missing_keys_read_as_the_model_defaults(self) -> None:
        """An older entry without user_name or changes"""
        legacy = {key: value for key, value in COMPLETE_LOG.items() if key not in ('user_name', 'changes')}

        serialized = serialize_object_log(legacy)

        assert serialized['user_name'] == CmdbObjectLog.UNKNOWN_USER_STRING
        assert serialized['changes'] == []

    def test_a_key_the_model_does_not_declare_is_not_passed_on(self) -> None:
        """A stale stored key stays in the database"""
        assert 'legacy_key' not in serialize_object_log({**COMPLETE_LOG, 'legacy_key': 'x'})

    def test_the_document_handed_in_is_not_changed(self) -> None:
        """The serializer builds a new dict"""
        document = {**COMPLETE_LOG, 'legacy_key': 'x'}

        serialize_object_log(document)

        assert document['legacy_key'] == 'x'


class TestObjectEntryActions:
    """The split lists the actions it wants, so MongoDB can read a date page off the index."""

    def test_every_action_but_delete(self) -> None:
        """A delete log has its own list"""
        assert object_entry_actions() == OBJECT_ENTRY_ACTIONS

    def test_derived_from_the_enum(self) -> None:
        """An action added to LogAction joins without a change to the helper"""
        assert set(object_entry_actions()) == {action.value for action in LogAction} - {LogAction.DELETE.value}

    def test_the_split_uses_in_not_ne(self) -> None:
        """$ne keeps an in-memory sort of every matching log; $in lets the index serve the page"""
        query = build_object_log_existence_filter([], object_exists=True)

        assert query[LogKey.ACTION.value] == {LogQueryOperator.IN.value: OBJECT_ENTRY_ACTIONS}
