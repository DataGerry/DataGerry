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
Unit tests for cmdb.manager.logs_manager.LogsManager

Pure tests: no Mongo. Each method is driven against a ``MagicMock(spec=LogsManager)`` with its
database collaborators (get_next_public_id / insert / iterate_query) stubbed, so only the
manager's own behavior is exercised - the static-field assembly in ``insert_log`` (public_id,
action value/name, log_type, kwargs merge) and the ``iterate`` aggregation -> IterationResult
binding plus its error wrapping. The aggregation against real MongoDB is covered incidentally by
the functional log-route suite.
"""
# pylint: disable=protected-access
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.manager.logs_manager import LogsManager
from cmdb.models.log_model.log_action_enum import LogAction
from cmdb.models.log_model.cmdb_object_log import CmdbObjectLog
from cmdb.framework.results import IterationResult

from cmdb.errors.manager import BaseManagerIterationError
# -------------------------------------------------------------------------------------------------------------------- #

MODULE_PATH: str = 'cmdb.manager.logs_manager'

NEXT_PUBLIC_ID: int = 51
OBJECT_ID: int = 42
USER_ID: int = 7
LOG_TYPE: str = 'CmdbObjectLog'
FROZEN_TIME: str = 'frozen-timestamp'
TOTAL_LOGS: int = 3

SERIALIZED_LOG: dict[str, Any] = {'public_id': NEXT_PUBLIC_ID, 'object_id': OBJECT_ID}


def _mock_manager() -> MagicMock:
    """A MagicMock standing in for a LogsManager instance."""
    return MagicMock(spec=LogsManager)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      insert_log                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestInsertLog:
    """``insert_log`` assembles the static log fields, merges kwargs, serializes and inserts."""

    def test_assembles_static_fields_and_returns_ack(self) -> None:
        """The new public_id, action value/name, log_type and merged kwargs reach ``CmdbLog``."""
        mgr = _mock_manager()
        mgr.get_next_public_id.return_value = NEXT_PUBLIC_ID
        mgr.insert.return_value = NEXT_PUBLIC_ID

        with patch(f'{MODULE_PATH}.CmdbLog') as cmdb_log_mock, \
             patch(f'{MODULE_PATH}.CmdbObjectLog.to_json', return_value=SERIALIZED_LOG) as to_json_mock, \
             patch(f'{MODULE_PATH}.datetime') as datetime_mock:
            datetime_mock.now.return_value = FROZEN_TIME

            result = LogsManager.insert_log(
                mgr,
                action=LogAction.CREATE,
                log_type=LOG_TYPE,
                object_id=OBJECT_ID,
                user_id=USER_ID,
            )

        mgr.get_next_public_id.assert_called_once_with(inc_id=True)
        _, build_kwargs = cmdb_log_mock.call_args
        assert build_kwargs['public_id'] == NEXT_PUBLIC_ID
        assert build_kwargs['action'] == LogAction.CREATE.value
        assert build_kwargs['action_name'] == LogAction.CREATE.name
        assert build_kwargs['log_type'] == LOG_TYPE
        assert build_kwargs['log_time'] == FROZEN_TIME
        assert build_kwargs['object_id'] == OBJECT_ID
        assert build_kwargs['user_id'] == USER_ID
        to_json_mock.assert_called_once_with(cmdb_log_mock.return_value)
        mgr.insert.assert_called_once_with(SERIALIZED_LOG)
        assert result == NEXT_PUBLIC_ID

    def test_kwargs_do_not_override_static_keys_silently(self) -> None:
        """A caller-supplied kwarg for a static key is merged last and wins (documents the merge order)."""
        mgr = _mock_manager()
        mgr.get_next_public_id.return_value = NEXT_PUBLIC_ID

        with patch(f'{MODULE_PATH}.CmdbLog') as cmdb_log_mock, \
             patch(f'{MODULE_PATH}.CmdbObjectLog.to_json', return_value=SERIALIZED_LOG), \
             patch(f'{MODULE_PATH}.datetime'):
            LogsManager.insert_log(
                mgr,
                action=LogAction.EDIT,
                log_type=LOG_TYPE,
                log_type_override=None,
                public_id=999,
            )

        _, build_kwargs = cmdb_log_mock.call_args
        # kwargs spread after log_init, so an explicit public_id kwarg takes precedence
        assert build_kwargs['public_id'] == 999


# -------------------------------------------------------------------------------------------------------------------- #
#                                                       iterate                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestIterate:
    """``iterate`` runs the aggregation and binds the rows to an IterationResult of CmdbObjectLog."""

    def test_wraps_query_result_in_iteration_result(self) -> None:
        """The aggregation result and total are forwarded to ``IterationResult`` with the model bound."""
        mgr = _mock_manager()
        rows = [{'public_id': 1}, {'public_id': 2}]
        mgr.iterate_query.return_value = (rows, TOTAL_LOGS)
        builder_params = MagicMock()

        with patch(f'{MODULE_PATH}.IterationResult') as iteration_result_cls:
            instance = iteration_result_cls.return_value
            result = LogsManager.iterate(mgr, builder_params)

        mgr.iterate_query.assert_called_once_with(builder_params, None, None)
        iteration_result_cls.assert_called_once_with(rows, TOTAL_LOGS)
        instance.convert_to.assert_called_once_with(CmdbObjectLog)
        assert result is instance

    def test_forwards_user_and_permission(self) -> None:
        """``user`` and ``permission`` are passed straight through to ``iterate_query``."""
        mgr = _mock_manager()
        mgr.iterate_query.return_value = ([], 0)
        builder_params = MagicMock()
        user = MagicMock()
        permission = MagicMock()

        with patch(f'{MODULE_PATH}.IterationResult'):
            LogsManager.iterate(mgr, builder_params, user, permission)

        mgr.iterate_query.assert_called_once_with(builder_params, user, permission)

    def test_query_failure_wraps_as_iteration_error(self) -> None:
        """Any failure during the aggregation is wrapped as ``BaseManagerIterationError``."""
        mgr = _mock_manager()
        mgr.iterate_query.side_effect = RuntimeError('aggregate boom')

        with pytest.raises(BaseManagerIterationError):
            LogsManager.iterate(mgr, MagicMock())
