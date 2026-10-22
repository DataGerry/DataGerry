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
Unit tests for objects_delete_cleanup.run_delete_cleanup_step

Pure: the step is a callable. Pinned: a step that raises one of its own typed errors is logged under the fixed marker
with the step and the object ids and answers False; a programming error propagates; every step tolerates a lost
connection and a lock timeout; the Rack and Port steps tolerate the 500 their own undo answers
"""
import logging
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import InternalServerError

from cmdb.errors.database import TRANSIENT_DATABASE_ERRORS
from cmdb.errors.manager.media_files_manager import MediaFileManagerUpdateError
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_constants import (
    DELETE_CLEANUP_INCOMPLETE_MARKER,
    DeleteCleanupStep,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_objects.objects_delete_cleanup import (
    DELETE_CLEANUP_STEP_ERRORS,
    run_delete_cleanup_step,
)
# -------------------------------------------------------------------------------------------------------------------- #

OBJECT_IDS: list[int] = [4711, 4712]

# Every (step, tolerated error class) pair, so each class of each step is exercised once
STEP_ERRORS: list[tuple[DeleteCleanupStep, type[Exception]]] = [
    (step, error) for step, errors in DELETE_CLEANUP_STEP_ERRORS.items() for error in errors
]


def _raiser(error: Exception):
    """A step that raises the given error"""
    def _step() -> None:
        raise error

    return _step


def _instance(error_class: type[Exception]) -> Exception:
    """An instance of an error class, whatever its constructor takes"""
    try:
        return error_class('the database failed')
    except TypeError:
        return error_class()


def test_every_step_names_its_errors() -> None:
    """A step without an entry would make the helper raise a KeyError instead of logging"""
    assert set(DELETE_CLEANUP_STEP_ERRORS) == set(DeleteCleanupStep)


@pytest.mark.parametrize('step', list(DeleteCleanupStep), ids=[step.value for step in DeleteCleanupStep])
def test_every_step_tolerates_a_lost_connection_and_a_lock_timeout(step: DeleteCleanupStep) -> None:
    """The object is gone, so a 503 / 423 would misreport the delete"""
    assert set(TRANSIENT_DATABASE_ERRORS) <= set(DELETE_CLEANUP_STEP_ERRORS[step])


@pytest.mark.parametrize('step', [DeleteCleanupStep.RACK, DeleteCleanupStep.PORTS], ids=['rack', 'ports'])
def test_the_hooks_with_an_undo_tolerate_its_500(step: DeleteCleanupStep, caplog) -> None:
    """undone_on_failure answers a 500 when it cannot finish; after an object delete that is a logged leftover"""
    with caplog.at_level(logging.ERROR):
        assert run_delete_cleanup_step(step, OBJECT_IDS, _raiser(InternalServerError('residue'))) is False

    assert DELETE_CLEANUP_INCOMPLETE_MARKER in caplog.text


@pytest.mark.parametrize('step, error_class', STEP_ERRORS,
                         ids=[f'{step.value}-{error.__name__}' for step, error in STEP_ERRORS])
def test_a_tolerated_failure_is_logged_with_the_step_and_the_ids(
        step: DeleteCleanupStep, error_class: type[Exception], caplog) -> None:
    """One line under the marker an operator alerts on, naming the step, the objects and the error"""
    with caplog.at_level(logging.ERROR):
        assert run_delete_cleanup_step(step, OBJECT_IDS, _raiser(_instance(error_class))) is False

    assert f'{DELETE_CLEANUP_INCOMPLETE_MARKER} step={step.value} objects={OBJECT_IDS}' in caplog.text
    assert error_class.__name__ in caplog.text


@pytest.mark.parametrize('step', list(DeleteCleanupStep), ids=[step.value for step in DeleteCleanupStep])
def test_a_programming_error_propagates(step: DeleteCleanupStep) -> None:
    """A bug is not a leftover: it still answers the route's 500"""
    with pytest.raises(KeyError):
        run_delete_cleanup_step(step, OBJECT_IDS, _raiser(KeyError('bug')))


def test_a_step_that_runs_through_answers_true_and_logs_nothing(caplog) -> None:
    """The ordinary case"""
    step = MagicMock()

    with caplog.at_level(logging.ERROR):
        assert run_delete_cleanup_step(DeleteCleanupStep.RELATIONS, OBJECT_IDS, step) is True

    step.assert_called_once_with()
    assert caplog.text == ''


def test_an_error_of_another_step_is_not_tolerated() -> None:
    """Each step names its own errors: the references step does not swallow a media-file failure"""
    with pytest.raises(MediaFileManagerUpdateError):
        run_delete_cleanup_step(DeleteCleanupStep.REFERENCES, OBJECT_IDS, _raiser(MediaFileManagerUpdateError('x')))
