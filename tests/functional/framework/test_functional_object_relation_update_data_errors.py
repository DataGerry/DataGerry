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
Functional tests: ``PUT /object_relations/<id>`` answers 400 only for data the model refuses

The update builds the stored document through ``CmdbObjectRelation.from_data`` / ``to_json``. What those refuse - their
declared ``CmdbObjectRelationInitFromDataError`` / ``CmdbObjectRelationToJsonError`` - is the request's data, a 400
naming the instance. Anything else is a bug and reaches the route's 500 instead of being reported as the caller's
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.errors.models.cmdb_object_relation import CmdbObjectRelationInitFromDataError, CmdbObjectRelationToJsonError
from cmdb.models.object_relation_model import CmdbObjectRelation

from tests.functional.framework.test_functional_object_relation_endpoints import (  # pylint: disable=unused-import
    ROUTE_URL,
    _payload,
    fixture_instances,
)
# -------------------------------------------------------------------------------------------------------------------- #


def _raise(failure: Exception) -> Any:
    """A stand-in classmethod body that raises ``failure``"""
    def _stub(*_args: Any, **_kwargs: Any) -> Any:
        raise failure

    return _stub


@pytest.mark.parametrize('method, failure', [
    ('from_data', CmdbObjectRelationInitFromDataError('unreadable')),
    ('to_json', CmdbObjectRelationToJsonError('unwritable')),
], ids=['from-data', 'to-json'])
def test_data_the_model_refuses_is_a_400(rest_api, instances, monkeypatch, method: str,
                                         failure: Exception) -> None:
    """Named by the instance"""
    public_id: int = rest_api.post(f'{ROUTE_URL}/', json=_payload()).get_json()['result_id']
    monkeypatch.setattr(CmdbObjectRelation, method, _raise(failure))

    response = rest_api.put(f'{ROUTE_URL}/{public_id}', json=_payload())

    assert response.status_code == HTTPStatus.BAD_REQUEST
    assert response.get_json()['message'] == f'The data of the ObjectRelation with ID:{public_id} is not usable!'


def test_a_bug_is_the_routes_500(rest_api, instances, monkeypatch) -> None:
    """Not reported as the caller's data"""
    public_id: int = rest_api.post(f'{ROUTE_URL}/', json=_payload()).get_json()['result_id']
    monkeypatch.setattr(CmdbObjectRelation, 'from_data', _raise(TypeError('a bug')))

    response = rest_api.put(f'{ROUTE_URL}/{public_id}', json=_payload())

    assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
    assert response.get_json()['message'] == (
        f'An internal server error occured while updating ObjectRelation with ID:{public_id}!'
    )
