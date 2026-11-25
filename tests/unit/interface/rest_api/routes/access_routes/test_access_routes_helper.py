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
Unit tests for the access rule routes' helpers

Past MagicMock managers, no database: a missing document is a 404 naming it; every problem of one write is one 400,
the rules that found nothing left out; a write a unique index refused - a lost race the pre-check could not see - is
the pre-check's own 400, and any other write failure is raised unchanged for the route's 500
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from werkzeug.exceptions import BadRequest, NotFound

from cmdb.errors.database import DocumentDuplicateKeyError
from cmdb.errors.manager.field_classes_manager import (
    FieldClassesManagerInsertError,
    FieldClassesManagerUpdateError,
)
from cmdb.models.access_model import CmdbFieldClass
from cmdb.interface.rest_api.routes.routes_helper import PROBLEM_SEPARATOR, abort_on_problems
from cmdb.interface.rest_api.routes.access_routes.access_routes_helper import (
    as_model_json,
    create_response,
    load_or_404,
    update_response,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 11
TAKEN: str = 'taken!'
CLASS: dict[str, Any] = {'name': 'compliance', 'label': 'Compliance', 'description': ''}
STORED_CLASS: dict[str, Any] = {'name': 'compliance', 'label': 'Compliance', 'public_id': PUBLIC_ID}


def _manager() -> MagicMock:
    """A field class manager stand-in carrying the real error map"""
    manager = MagicMock()
    manager.model = CmdbFieldClass
    manager.exceptions = {'insert': FieldClassesManagerInsertError, 'update': FieldClassesManagerUpdateError}

    return manager


def _duplicate(error: type[Exception]) -> Exception:
    """A manager error carrying the unique index's refusal, as the manager raises it"""
    cause = DocumentDuplicateKeyError('E11000')
    wrapped: Exception = error(cause)
    wrapped.__cause__ = cause

    return wrapped


class TestLoadOr404:
    """A stored document, or a 404 naming it."""

    def test_the_stored_document_through_its_model(self) -> None:
        """Read as a dict, answered as the model writes it: every key in the model's order, a missing one filled"""
        manager = _manager()
        manager.get_item.return_value = STORED_CLASS

        loaded: dict[str, Any] = load_or_404(manager, PUBLIC_ID, 'Field class')

        assert list(loaded) == ['public_id', 'name', 'label', 'description']
        assert loaded == {**STORED_CLASS, 'description': ''}
        manager.get_item.assert_called_once_with(PUBLIC_ID, as_dict=True)

    def test_several_documents_through_the_model(self) -> None:
        """Each one as the model writes it, in the order given"""
        second: dict[str, Any] = {**STORED_CLASS, 'public_id': PUBLIC_ID + 1}

        assert [item['public_id'] for item in as_model_json(CmdbFieldClass, [STORED_CLASS, second])] == [
            PUBLIC_ID, PUBLIC_ID + 1]

    def test_a_missing_document(self) -> None:
        """404 naming the label and the id"""
        manager = _manager()
        manager.get_item.return_value = None

        with pytest.raises(NotFound) as raised:
            load_or_404(manager, PUBLIC_ID, 'Field class')

        assert raised.value.description == f'Field class {PUBLIC_ID} does not exist!'


class TestAbortOnProblems:
    """Every problem in one 400."""

    @pytest.mark.parametrize('problems', [[], [None, None]], ids=['none', 'all-clear'])
    def test_nothing_found_goes_on(self, problems: list[str | None]) -> None:
        """No exception"""
        abort_on_problems(problems)

    def test_the_problems_found_are_joined(self) -> None:
        """The None entries left out"""
        with pytest.raises(BadRequest) as raised:
            abort_on_problems(['first', None, 'second'])

        assert raised.value.description == PROBLEM_SEPARATOR.join(['first', 'second'])


class TestALostRace:
    """A unique index refusing the write is the pre-check's 400; anything else is raised."""

    def test_a_create(self) -> None:
        """Insert refused by the index"""
        manager = _manager()
        manager.insert_item.side_effect = _duplicate(FieldClassesManagerInsertError)

        with pytest.raises(BadRequest) as raised:
            create_response(manager, CmdbFieldClass, CLASS, TAKEN)

        assert raised.value.description == TAKEN

    def test_an_update(self) -> None:
        """Update refused by the index"""
        manager = _manager()
        manager.update_item.side_effect = _duplicate(FieldClassesManagerUpdateError)

        with pytest.raises(BadRequest) as raised:
            update_response(manager, CmdbFieldClass, PUBLIC_ID, dict(CLASS), TAKEN)

        assert raised.value.description == TAKEN

    def test_another_failure_is_raised_unchanged(self) -> None:
        """For the route's 500"""
        manager = _manager()
        failure = FieldClassesManagerInsertError('disk full')
        manager.insert_item.side_effect = failure

        with pytest.raises(FieldClassesManagerInsertError) as raised:
            create_response(manager, CmdbFieldClass, CLASS, TAKEN)

        assert raised.value is failure
