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
Unit tests for cmdb.framework.port.cascade

A port is stored outside its owner's document, so this cascade is the only thing that removes it when
the object goes. Pure tests: the manager is a mock, so what is asserted is that the removal is a
single statement and that it is never skipped for a reason the user cannot see
"""
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from cmdb.framework.port.cascade import delete_ports_of_object
from cmdb.interface.rest_api.routes.port_routes import port_object_hooks
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_ID: int = 5000


def _manager(removed: int = 0) -> MagicMock:
    """A PortsManager stand-in reporting the given number of removed ports."""
    manager = MagicMock(name='ports_manager')
    manager.delete_ports_of_object.return_value = removed

    return manager


def _object(public_id: Any = OBJECT_ID) -> dict[str, Any]:
    """A deleted CmdbObject document."""
    return {'public_id': public_id, 'type_id': 42}


def test_removes_the_ports_in_one_statement() -> None:
    """One delete for the whole object, not one per port"""
    manager = _manager(removed=3)

    assert delete_ports_of_object(manager, _object()) == 3
    manager.delete_ports_of_object.assert_called_once_with(OBJECT_ID)


def test_an_object_without_ports_is_a_no_op() -> None:
    """The common case: one indexed delete that matches nothing"""
    manager = _manager(removed=0)

    assert delete_ports_of_object(manager, _object()) == 0


@pytest.mark.parametrize('public_id', [None, 'not-an-int', 1.5], ids=['none', 'string', 'float'])
def test_a_document_without_an_integer_public_id_is_skipped(public_id: Any) -> None:
    """
    A malformed document must not turn into a delete with a garbage filter

    `{'object_id': None}` would match every port whose owner key is missing, which is the kind of
    filter that empties a collection.
    """
    manager = _manager()

    assert delete_ports_of_object(manager, _object(public_id)) == 0
    manager.delete_ports_of_object.assert_not_called()


def test_the_type_flag_is_not_consulted() -> None:
    """
    Cleanup may not depend on `uses_ports`

    The flag can be turned off after the ports were created; gating the cascade on it would orphan
    exactly the rows the cascade exists to remove. The document carries no flag here and the ports go
    anyway.
    """
    manager = _manager(removed=1)

    assert delete_ports_of_object(manager, {'public_id': OBJECT_ID}) == 1


def test_reports_the_removal(caplog) -> None:
    """A cascade that removed rows says so, so an unexpected mass delete is traceable"""
    manager = _manager(removed=7)

    with caplog.at_level('INFO'):
        delete_ports_of_object(manager, _object())

    assert '7 port(s)' in caplog.text


def test_says_nothing_when_there_was_nothing_to_remove(caplog) -> None:
    """Every object deletion runs this; a log line per deletion would be noise"""
    manager = _manager(removed=0)

    with caplog.at_level('INFO'):
        delete_ports_of_object(manager, _object())

    assert caplog.text == ''


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the hook the /objects routes call                                              #
# -------------------------------------------------------------------------------------------------------------------- #
HOOK_PATH: str = 'cmdb.interface.rest_api.routes.port_routes.port_object_hooks'


def test_the_hook_resolves_the_manager_and_delegates() -> None:
    """The hook is request-shaped; the statement itself lives in the cascade"""
    manager = _manager(removed=2)

    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager', return_value=manager):
        port_object_hooks.handle_object_deleted(MagicMock(), _object())

    manager.delete_ports_of_object.assert_called_once_with(OBJECT_ID)


@pytest.mark.parametrize('public_id', [None, 'not-an-int'], ids=['none', 'string'])
def test_the_hook_resolves_no_manager_for_a_malformed_document(public_id: Any) -> None:
    """
    Every object deletion runs this hook, so a malformed document must not cost a manager

    ManagerProvider needs an application context; building one for a document that cannot have ports
    would be pure waste on a path that runs for every delete.
    """
    with patch(f'{HOOK_PATH}.ManagerProvider.get_manager') as get_manager:
        port_object_hooks.handle_object_deleted(MagicMock(), _object(public_id))

    get_manager.assert_not_called()
