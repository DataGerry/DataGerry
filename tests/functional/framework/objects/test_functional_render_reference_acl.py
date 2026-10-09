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
What the reference-resolving surfaces answer a caller who may not read a referenced object

Every surface that renders with reference resolution - the object view, the rendered object list, the
search with `?resolve=true`, the object export - reads a referenced object through the caller's READ ACL.
Requested as the admin group (which may read the hidden type) and as a group that may not (the default
user group; for the export, a group holding the export right alone): the hidden object's value reaches
the first and never the second. The MDS reference routes answer
the object's own reference block, and the batch route blanks an object the caller may not read
"""
import json
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.rendering.render_constants import RenderedFieldKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.type_reference import TypeReference
from cmdb.models.type_model.type_reference_key_enum import TypeReferenceKey
from tests.utils import reference_acl_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/objects'
SEARCH_URL: str = '/search/'
EXPORT_URL: str = '/exporter/'
JSON_EXPORT_CLASS: str = 'JsonExportFormat'
RENDER_VIEW: str = 'render'

MAIN_IDS_FILTER: str = json.dumps({'public_id': {'$in': [seed.MAIN_ID, seed.SECOND_MAIN_ID]}})
MAIN_TYPE_FILTER: str = json.dumps({'type_id': seed.MAIN_TYPE_ID})
SEARCH_BODY: str = json.dumps([{'searchText': seed.MAIN_VALUE, 'searchForm': 'text'}])


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the reference-ACL fixture for each test and removes it after."""
    seed.seed(database_manager, database_name)
    yield
    seed.purge(database_manager, database_name)


def _as_default_user() -> dict[str, Any]:
    """The request keywords that send it as the seeded default-group user."""
    return {'user': seed.default_user()}


def _field(rendered: dict[str, Any], name: str) -> dict[str, Any]:
    """The rendered field with the given name."""
    return next(field for field in rendered['fields'] if field[FieldKey.NAME] == name)


SURFACES: list[tuple[str, str, dict[str, Any]]] = [
    ('object view', 'get', {'path': f'{ROUTE_URL}/{seed.MAIN_ID}'}),
    ('rendered list', 'get', {'path': f'{ROUTE_URL}/?view=render&limit=0&filter={MAIN_IDS_FILTER}'}),
    ('search', 'post', {'path': f'{SEARCH_URL}?limit=0&resolve=true', 'data': SEARCH_BODY,
                        'content_type': 'application/json'}),
]

# The render view is what writes a reference as the referenced object's summary line
EXPORT_PATH: str = f'{EXPORT_URL}?filter={MAIN_TYPE_FILTER}&classname={JSON_EXPORT_CLASS}&view={RENDER_VIEW}'


def _request(rest_api, method: str, request: dict[str, Any], **kwargs: Any):
    """Sends one surface's request."""
    request = dict(request)

    return getattr(rest_api, method)(request.pop('path'), **request, **kwargs)


@pytest.mark.parametrize('method, request_kwargs', [(method, request) for _name, method, request in SURFACES],
                         ids=[name for name, _method, _request in SURFACES])
class TestEverySurface:
    """The same rule on each reference-resolving surface."""

    def test_the_admin_sees_the_hidden_value(self, rest_api, method: str, request_kwargs: dict[str, Any]) -> None:
        """The control: the surface does resolve the reference for a reader of its type"""
        response = _request(rest_api, method, request_kwargs)

        assert response.status_code == HTTPStatus.OK
        assert seed.HIDDEN_VALUE in response.get_data(as_text=True)

    def test_the_default_user_does_not(self, rest_api, method: str, request_kwargs: dict[str, Any]) -> None:
        """The surface answers, and the hidden object's value is nowhere in it"""
        response = _request(rest_api, method, request_kwargs, **_as_default_user())

        assert response.status_code == HTTPStatus.OK
        assert seed.MAIN_VALUE in response.get_data(as_text=True)
        assert seed.HIDDEN_VALUE not in response.get_data(as_text=True)


class TestTheObjectExport:
    """The render view of the object export, for a caller who holds the export right."""

    def test_the_admin_exports_the_hidden_summary(self, rest_api) -> None:
        """The control: the reference column carries the hidden object's summary"""
        response = rest_api.get(EXPORT_PATH)

        assert response.status_code == HTTPStatus.OK
        assert seed.HIDDEN_VALUE in response.get_data(as_text=True)

    def test_the_exporter_does_not(self, rest_api) -> None:
        """The export is produced, without the hidden object's value"""
        response = rest_api.get(EXPORT_PATH, user=seed.exporter_user())

        assert response.status_code == HTTPStatus.OK
        assert seed.MAIN_VALUE in response.get_data(as_text=True)
        assert seed.HIDDEN_VALUE not in response.get_data(as_text=True)


class TestTheObjectView:
    """GET /objects/<id> for the default user."""

    def test_the_reference_keeps_its_id_and_answers_the_empty_block(self, rest_api) -> None:
        """The stored id survives a save of the whole object; the block says nothing about the target"""
        rendered = rest_api.get(f'{ROUTE_URL}/{seed.MAIN_ID}', **_as_default_user()).get_json()
        field = _field(rendered, seed.REF_FIELD)

        assert field[FieldKey.VALUE] == seed.HIDDEN_ID
        assert field[RenderedFieldKey.REFERENCE] == TypeReference.to_json(TypeReference.empty())

    def test_the_render_reports_no_problem(self, rest_api) -> None:
        """A hidden reference is no degraded render"""
        rendered = rest_api.get(f'{ROUTE_URL}/{seed.MAIN_ID}', **_as_default_user()).get_json()

        assert rendered['render_problems'] == []


class TestTheMdsReferenceRoutes:
    """GET /objects/<id>/mds_reference[s]."""

    def test_the_single_route_answers_the_objects_own_reference(self, rest_api) -> None:
        """The block names the object, its type and its summary values"""
        reference = rest_api.get(f'{ROUTE_URL}/{seed.MAIN_ID}/mds_reference').get_json()

        assert reference[TypeReferenceKey.OBJECT_ID.value] == seed.MAIN_ID
        assert reference[TypeReferenceKey.TYPE_ID.value] == seed.MAIN_TYPE_ID
        assert seed.MAIN_VALUE in [summary['value'] for summary in reference[TypeReferenceKey.SUMMARIES.value]]

    def test_the_single_route_refuses_a_hidden_object(self, rest_api) -> None:
        """Asked for directly, a hidden object is a 403, as GET /objects/<id> answers"""
        response = rest_api.get(f'{ROUTE_URL}/{seed.HIDDEN_ID}/mds_reference', **_as_default_user())

        assert response.status_code == HTTPStatus.FORBIDDEN

    def test_the_batch_route_blanks_a_hidden_object(self, rest_api) -> None:
        """The hidden id answers the empty reference; the readable one its block; the batch is a 200"""
        response = rest_api.get(
            f'{ROUTE_URL}/{seed.MAIN_ID}/mds_references?objectIDs={seed.MAIN_ID},{seed.HIDDEN_ID}',
            **_as_default_user(),
        )
        body: dict[str, Any] = response.get_json()

        assert response.status_code == HTTPStatus.OK
        assert body[str(seed.HIDDEN_ID)] == TypeReference.to_json(TypeReference.empty())
        assert body[str(seed.MAIN_ID)][TypeReferenceKey.OBJECT_ID.value] == seed.MAIN_ID

    def test_the_batch_route_answers_the_admin_every_block(self, rest_api) -> None:
        """The control: a reader of the hidden type gets its block"""
        body: dict[str, Any] = rest_api.get(
            f'{ROUTE_URL}/{seed.MAIN_ID}/mds_references?objectIDs={seed.MAIN_ID},{seed.HIDDEN_ID}',
        ).get_json()

        assert body[str(seed.HIDDEN_ID)][TypeReferenceKey.OBJECT_ID.value] == seed.HIDDEN_ID
