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
Functional tests: a client ``$lookup`` into the objects sees only what the caller may read

Seeded with ``tests/utils/location_acl_seed`` (a VISIBLE type and a HIDDEN one only the admin group may read); the
seed's editor group is given the object and type view rights. Before the fix a client join pulled HIDDEN objects into the
outer row and a ``$match`` on the joined values answered yes / no about them through the total - an oracle that
read any hidden value one guess at a time. Pinned here, as the editor:

  - the oracle is closed: a right and a wrong guess about a HIDDEN value answer the same total (none), on the
    object list (the type-ACL path) and on the type list (``parse_parameters``, a route that never applies the
    object ACL itself), in the ``pipeline`` form, the ``localField`` / ``foreignField`` form and a nested join
  - a join still finds what the caller may read, and the admin - whom HIDDEN grants - still joins it
  - the ``filter`` echoed in the response is the one the client sent: the denied type ids never come back
"""
from http import HTTPStatus
from json import dumps
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.location_model.location_constants import RootLocationDefault
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model.type_constants import TypeRight
from tests.utils import location_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

OBJECTS_URL: str = '/objects/'
TYPES_URL: str = '/types/'
# What the joined documents land under in the outer row
JOIN_ALIAS: str = 'joined'
# A guess no seeded value starts with
WRONG_GUESS: str = '^nothing-like-it'
# The number of objects the editor may read in the seed - the rows a matching guess answers on the object list
EDITOR_READABLE_OBJECT_COUNT: int = 6


def _prefix(value: str) -> str:
    """A regex anchored on the first characters of a seeded value - a 'right guess'."""
    return f'^{value[:8]}'


def _join_by_id(target_id: int, guess: str) -> list[dict[str, Any]]:
    """The oracle in the ``pipeline`` form: join one object by id, then test its values."""
    return [
        {'$lookup': {'from': CmdbObject.COLLECTION, 'pipeline': [{'$match': {'public_id': target_id}}],
                     'as': JOIN_ALIAS}},
        {'$match': {f'{JOIN_ALIAS}.fields.value': {'$regex': guess}}},
    ]


def _join_by_field(guess: str) -> list[dict[str, Any]]:
    """The oracle in the ``localField`` / ``foreignField`` form: join every object sharing the row's author."""
    return [
        {'$lookup': {'from': CmdbObject.COLLECTION, 'localField': 'author_id', 'foreignField': 'author_id',
                     'as': JOIN_ALIAS}},
        {'$match': {f'{JOIN_ALIAS}.fields.value': {'$regex': guess}}},
    ]


def _nested_join(target_id: int, guess: str) -> list[dict[str, Any]]:
    """The oracle one level down: a join whose own pipeline joins the objects again."""
    inner: dict[str, Any] = {'$lookup': {'from': CmdbObject.COLLECTION,
                                         'pipeline': [{'$match': {'public_id': target_id}}], 'as': 'inner'}}
    return [
        {'$lookup': {'from': CmdbObject.COLLECTION, 'pipeline': [{'$match': {'public_id': seed.VISIBLE_ID}}, inner],
                     'as': JOIN_ALIAS}},
        {'$match': {f'{JOIN_ALIAS}.inner.fields.value': {'$regex': guess}}},
    ]


@pytest.fixture(name='seeded', autouse=True)
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """The location ACL seed; its editor group may view objects and types but not READ the HIDDEN type"""
    seed.seed(database_manager, database_name, RootLocationDefault.PUBLIC_ID)
    database_manager.get_collection(CmdbUserGroup.COLLECTION, database_name).update_one(
        {'public_id': seed.EDITOR_GROUP_ID},
        {'$push': {'rights': {'$each': [ObjectRightName.VIEW.value, TypeRight.VIEW.value]}}},
    )
    yield
    seed.purge(database_manager, database_name)


def _editor() -> dict[str, Any]:
    """The request kwargs that send it as the seed's editor, who may not read HIDDEN"""
    return {'user': seed.location_editor()}


def _total(rest_api, url: str, pipeline: list[dict[str, Any]], **kwargs: Any) -> int:
    """The total a list route answers for a filter; the request must succeed."""
    response = rest_api.get(f'{url}?limit=1&filter={dumps(pipeline)}', **kwargs)

    assert response.status_code == HTTPStatus.OK, response.get_data(as_text=True)

    return response.get_json()['total']


class TestTheOracleIsClosed:
    """As the editor, a guess about a HIDDEN value answers nothing - right or wrong alike."""

    @pytest.mark.parametrize('build', [
        pytest.param(lambda guess: _join_by_id(seed.HIDDEN_ID, guess), id='pipeline form'),
        pytest.param(_join_by_field, id='localField form'),
        pytest.param(lambda guess: _nested_join(seed.HIDDEN_ID, guess), id='nested join'),
    ])
    def test_a_right_guess_answers_like_a_wrong_one_on_the_object_list(self, rest_api, build) -> None:
        """The join no longer sees the HIDDEN object, so its value cannot steer the total"""
        right: int = _total(rest_api, OBJECTS_URL, build(_prefix(seed.HIDDEN_VALUE)), **_editor())
        wrong: int = _total(rest_api, OBJECTS_URL, build(WRONG_GUESS), **_editor())

        assert right == wrong == 0

    def test_a_route_without_an_object_acl_is_closed_too(self, rest_api) -> None:
        """
        The type list runs the filter over types and never applies the object ACL - the scoping at the
        parameter boundary covers it all the same
        """
        right: int = _total(rest_api, TYPES_URL, _join_by_id(seed.HIDDEN_ID, _prefix(seed.HIDDEN_VALUE)), **_editor())

        assert right == 0


class TestReadableJoinsStillWork:
    """The scoping removes what the caller may not read, and nothing else."""

    def test_a_join_finds_a_readable_object(self, rest_api) -> None:
        """A VISIBLE object joined and matched by its value still answers every readable row"""
        pipeline = _join_by_id(seed.VISIBLE_ID, _prefix(seed.VISIBLE_VALUE))

        assert _total(rest_api, OBJECTS_URL, pipeline, **_editor()) == EDITOR_READABLE_OBJECT_COUNT

    def test_the_admin_still_joins_the_hidden_type(self, rest_api) -> None:
        """HIDDEN grants the admin group, so nothing is denied and the join is left as sent"""
        assert _total(rest_api, OBJECTS_URL, _join_by_id(seed.HIDDEN_ID, _prefix(seed.HIDDEN_VALUE))) > 0


class TestTheEcho:
    """The `parameters.filter` a list answers is the client's, not the scoped one."""

    def test_the_echoed_filter_is_the_one_sent(self, rest_api) -> None:
        """The scoped join carries the denied type ids; the echo must not"""
        pipeline = _join_by_id(seed.HIDDEN_ID, WRONG_GUESS)
        response = rest_api.get(f'{OBJECTS_URL}?limit=1&filter={dumps(pipeline)}', **_editor())

        assert response.get_json()['parameters']['filter'] == pipeline
        assert str(seed.HIDDEN_TYPE_ID) not in dumps(response.get_json()['parameters'])
