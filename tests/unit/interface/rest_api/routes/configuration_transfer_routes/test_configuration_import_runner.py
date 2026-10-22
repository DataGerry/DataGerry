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
Unit tests for ``configuration_import_runner.import_transfer_document`` - the one import pipeline

Every step it runs is patched at the runner's path (each has tests of its own, and the import route's functional and
integration suites run the real pipeline), so what is pinned is the pipeline itself: the order of its steps, that a
refusal stops every step after it - nothing is written before the last - and what each step is handed
"""
from contextlib import contextmanager
from typing import Any, Iterator
from unittest.mock import MagicMock, call, patch

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.manager.manager_provider_model import ManagerType
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner import (
    import_transfer_document,
)
from cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_transfer_route_constants import (
    IMPORT_UNDO_INCOMPLETE_MESSAGE,
    NO_DB_VERSION_MESSAGE,
    NOT_RESET_MESSAGE,
)
# -------------------------------------------------------------------------------------------------------------------- #

RUNNER_PATH: str = 'cmdb.interface.rest_api.routes.configuration_transfer_routes.configuration_import_runner'
DB_VERSION: int = 20261021
USER_ID: int = 1
IMPORTED: dict[str, int] = {'types': 3, 'categories': 1}
BLOCKERS: list[str] = ['framework.objects']
FILE_PROBLEMS: list[str] = ['a file problem']
IMPORT_PROBLEMS: list[str] = ['an import problem']
TEMPLATE_PROBLEMS: list[str] = ['a template problem']
HTTP_BAD_REQUEST: int = 400
HTTP_SERVER_ERROR: int = 500

# The steps in the runner's order
STEPS: list[str] = [
    'find_import_blockers', 'read_database_version', 'find_file_problems', 'migrate_transfer_file',
    'build_import_context', 'find_import_problems', 'reconcile_template_copies', 'undone_on_failure',
    'import_configuration',
]


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A bare app carrying a database manager, for current_app and abort()"""
    app = Flask(__name__)
    app.database_manager = MagicMock(name='database_manager')

    return app


@pytest.fixture(name='steps')
def fixture_steps(flask_app: Flask) -> Any:
    """Every step patched under one parent mock, in a request context; managers handed out per ManagerType"""
    parent = MagicMock()
    parent.find_import_blockers.return_value = []
    parent.read_database_version.return_value = DB_VERSION
    parent.find_file_problems.return_value = []
    parent.find_import_problems.return_value = []
    parent.reconcile_template_copies.return_value = []
    parent.import_configuration.return_value = IMPORTED
    managers: dict[ManagerType, MagicMock] = {}

    @contextmanager
    def _ledger(message: str) -> Iterator[MagicMock]:
        parent.undone_on_failure(message)
        yield parent.ledger

    patchers = [patch(f'{RUNNER_PATH}.{name}', getattr(parent, name)) for name in STEPS if name != 'undone_on_failure']
    patchers += [
        patch(f'{RUNNER_PATH}.undone_on_failure', _ledger),
        patch(f'{RUNNER_PATH}.abort_with_problems', parent.abort_with_problems),
        patch(f'{RUNNER_PATH}.build_transfer_components', parent.build_transfer_components),
        patch(f'{RUNNER_PATH}.ManagerProvider.get_manager',
              side_effect=lambda manager_type, _user: managers.setdefault(manager_type, MagicMock(name=manager_type))),
    ]

    for patcher in patchers:
        patcher.start()

    with flask_app.test_request_context():
        yield parent, managers

    for patcher in patchers:
        patcher.stop()


def _user() -> MagicMock:
    """The importing administrator account"""
    user = MagicMock()
    user.public_id = USER_ID

    return user


def test_the_steps_run_in_order_and_hand_on_their_results(flask_app: Flask, steps: Any) -> None:
    """Blockers, version, envelope, migration, context, problems, reconcile - then the ledgered write"""
    parent, managers = steps
    transfer_file, user = {'a': 'file'}, _user()

    assert import_transfer_document(transfer_file, user) == IMPORTED

    migrated = parent.migrate_transfer_file.return_value
    context = parent.build_import_context.return_value
    assert [entry for entry in parent.mock_calls if entry[0] in STEPS] == [
        call.find_import_blockers(managers[ManagerType.TYPES]),
        call.read_database_version(managers[ManagerType.SETTINGS]),
        call.find_file_problems(transfer_file, DB_VERSION),
        call.migrate_transfer_file(flask_app.database_manager, transfer_file, DB_VERSION,
                                   parent.migrate_transfer_file.call_args.args[3]),
        call.build_import_context(user),
        call.find_import_problems(migrated, DB_VERSION, context),
        call.reconcile_template_copies(migrated, context),
        call.undone_on_failure(IMPORT_UNDO_INCOMPLETE_MESSAGE),
        call.import_configuration(
            parent.build_transfer_components.return_value, migrated,
            (managers[ManagerType.SECTION_TEMPLATES], managers[ManagerType.USER_SETTINGS]), parent.ledger, USER_ID,
        ),
    ]


def test_every_problem_list_is_judged(steps: Any) -> None:
    """The envelope, the import's checks and the template reconcile - each through the one refusal"""
    parent, _managers = steps
    parent.find_file_problems.return_value = FILE_PROBLEMS
    parent.find_import_problems.return_value = IMPORT_PROBLEMS
    parent.reconcile_template_copies.return_value = TEMPLATE_PROBLEMS

    import_transfer_document({}, _user())

    assert parent.abort_with_problems.call_args_list == [call(FILE_PROBLEMS), call(IMPORT_PROBLEMS),
                                                         call(TEMPLATE_PROBLEMS)]


def test_a_system_that_is_not_reset_is_refused_before_anything_else(steps: Any) -> None:
    """400 naming the blockers; not even the version is read"""
    parent, _managers = steps
    parent.find_import_blockers.return_value = BLOCKERS

    with pytest.raises(HTTPException) as exc_info:
        import_transfer_document({}, _user())

    assert (exc_info.value.code, exc_info.value.description) == (
        HTTP_BAD_REQUEST, NOT_RESET_MESSAGE.format(collections=BLOCKERS))
    parent.read_database_version.assert_not_called()


def test_a_database_without_a_version_is_the_servers_fault(steps: Any) -> None:
    """500, before the file is judged"""
    parent, _managers = steps
    parent.read_database_version.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        import_transfer_document({}, _user())

    assert (exc_info.value.code, exc_info.value.description) == (HTTP_SERVER_ERROR, NO_DB_VERSION_MESSAGE)
    parent.find_file_problems.assert_not_called()


class _Refused(Exception):
    """What the patched refusal raises for a non-empty problem list"""


def _refuse_problems(problems: list[str]) -> None:
    """Stands in for abort_with_problems: refuses a non-empty list, passes an empty one"""
    if problems:
        raise _Refused(problems)


@pytest.mark.parametrize('refusing_step', ['find_file_problems', 'find_import_problems', 'reconcile_template_copies'])
def test_a_refused_file_writes_nothing(steps: Any, refusing_step: str) -> None:
    """A problem list that refuses stops every step after it - the write above all"""
    parent, _managers = steps
    getattr(parent, refusing_step).return_value = ['refused']
    parent.abort_with_problems.side_effect = _refuse_problems

    with pytest.raises(_Refused):
        import_transfer_document({}, _user())

    later: list[str] = STEPS[STEPS.index(refusing_step) + 1:]
    assert not [entry for entry in parent.mock_calls if entry[0] in later]
    parent.import_configuration.assert_not_called()
