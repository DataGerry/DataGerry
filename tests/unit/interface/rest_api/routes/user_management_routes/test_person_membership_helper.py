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
Unit tests for the person / person-group reference guard

Pure tests: no Mongo. ``abort_on_unknown_references`` is the one place both membership route files ask
whether the ids a payload references exist, so what is pinned here is what a caller may rely on:
nothing is checked when nothing is referenced, the check costs one lookup rather than one per id, and
the refusal names the ids that are missing so the client can fix the payload
"""
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import Flask
from werkzeug.exceptions import HTTPException

from cmdb.interface.rest_api.routes.user_management_routes.person_membership_helper import (
    abort_on_unknown_references,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400
LABEL: str = 'PersonGroup'


@pytest.fixture(name='flask_app')
def fixture_flask_app() -> Flask:
    """A minimal Flask app, since abort() needs an application context."""
    return Flask(__name__)


def _manager(existing: set[int]) -> MagicMock:
    """A manager stub reporting the given public_ids as existing"""
    manager = MagicMock()
    manager.find_existing_public_ids.return_value = existing

    return manager


def test_passes_when_every_reference_exists(flask_app: Flask) -> None:
    """The happy path writes nothing and raises nothing."""
    with flask_app.app_context():
        abort_on_unknown_references(_manager({1, 2}), [1, 2], LABEL)


def test_refuses_and_names_the_missing_ids(flask_app: Flask) -> None:
    """
    The message carries the ids, because the client cannot otherwise tell which reference was wrong

    A payload naming a dozen groups would otherwise be rejected with nothing to act on.
    """
    with flask_app.app_context():
        with pytest.raises(HTTPException) as caught:
            abort_on_unknown_references(_manager({1}), [1, 7, 9], LABEL)

    assert caught.value.code == HTTP_BAD_REQUEST
    assert '7' in caught.value.description and '9' in caught.value.description
    assert LABEL in caught.value.description


def test_reports_the_missing_ids_in_a_stable_order(flask_app: Flask) -> None:
    """Sorted, so the message does not depend on set iteration order between runs."""
    with flask_app.app_context():
        with pytest.raises(HTTPException) as caught:
            abort_on_unknown_references(_manager(set()), [9, 7], LABEL)

    assert '[7, 9]' in caught.value.description


def test_checks_nothing_for_an_empty_selection(flask_app: Flask) -> None:
    """A payload referencing nothing must not cost a query."""
    manager = _manager(set())

    with flask_app.app_context():
        abort_on_unknown_references(manager, [], LABEL)

    manager.find_existing_public_ids.assert_not_called()


def test_checks_nothing_for_a_missing_selection(flask_app: Flask) -> None:
    """None is what a payload omitting the membership key produces."""
    manager = _manager(set())

    with flask_app.app_context():
        abort_on_unknown_references(manager, None, LABEL)

    manager.find_existing_public_ids.assert_not_called()


def test_asks_the_manager_once_for_the_whole_list(flask_app: Flask) -> None:
    """One projected '$in' query, not one read per referenced id."""
    manager = _manager({1, 2, 3})

    with flask_app.app_context():
        abort_on_unknown_references(manager, [1, 2, 3], LABEL)

    manager.find_existing_public_ids.assert_called_once()


def test_a_duplicate_reference_is_asked_about_once(flask_app: Flask) -> None:
    """A repeated id is the same reference, and must not be reported twice either."""
    manager = _manager(set())

    with flask_app.app_context():
        with pytest.raises(HTTPException) as caught:
            abort_on_unknown_references(manager, [4, 4], LABEL)

    assert '[4]' in caught.value.description


def test_the_label_names_what_the_ids_refer_to(flask_app: Flask) -> None:
    """The two route files pass different labels, and the message has to say which side failed."""
    with flask_app.app_context():
        with pytest.raises(HTTPException) as caught:
            abort_on_unknown_references(_manager(set()), [1], 'Person')

    description: Any = caught.value.description

    assert 'Person ID(s)' in description
