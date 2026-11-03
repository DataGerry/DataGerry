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
Functional coverage for what the DocapiTemplate update, delete and render routes answer when a read fails or the
template vanishes under them

  - a failed read of the addressed template (update, delete, render) and of the render's object is the routes'
    400 with that read's message - patched at the database delegate, and once for real: a stored template without
    its ``name`` does not fit the model
  - a programming error in the same read is not dressed up as that 400: it answers 500
  - a template deleted between the route's read and its write answers 404 on update and delete, never a 200 - the
    update writes nothing (no upsert)
"""
from http import HTTPStatus
from typing import Any
from unittest.mock import patch

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.docapi_templates_manager import DocapiTemplatesManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_OBJECT_NOT_READABLE_MSG,
    TEMPLATE_MISSING_MSG,
    TEMPLATE_NOT_READABLE_MSG,
)
from cmdb.errors.manager import BaseManagerGetError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError
# -------------------------------------------------------------------------------------------------------------------- #

CRUD_URL: str = '/docapi/template'
TEMPLATE_ID: int = 81201
NAMELESS_TEMPLATE_ID: int = 81202
TEMPLATE_NAME: str = 'tpl-read-failures'
OBJECT_ID: int = 81901
BUG: str = 'a programming error'
DB_FAILURE: str = 'the read failed'
TEMPLATE_READ_DELEGATE: str = 'get_one'

TEMPLATE_PAYLOAD: dict[str, Any] = {'public_id': TEMPLATE_ID, 'name': TEMPLATE_NAME, 'label': 'Template',
                                    'active': True, 'template_data': '<p>{{ }}</p>'}


def _put(rest_api, public_id: int) -> Any:
    """PUT the template payload addressed to ``public_id``"""
    return rest_api.put(f'{CRUD_URL}/', json={**TEMPLATE_PAYLOAD, 'public_id': public_id})


def _delete(rest_api, public_id: int) -> Any:
    """DELETE the template ``public_id``"""
    return rest_api.delete(f'{CRUD_URL}/{public_id}')


def _render(rest_api, public_id: int) -> Any:
    """Render the template ``public_id`` for OBJECT_ID"""
    return rest_api.get(f'{CRUD_URL}/{public_id}/render/{OBJECT_ID}')


# The three routes that read the addressed template first
TEMPLATE_READERS: list[Any] = [_put, _delete, _render]
TEMPLATE_READER_IDS: list[str] = ['update', 'delete', 'render']


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The document-generator routes are licence-gated; every feature is licensed here"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='templates', autouse=True)
def fixture_templates(database_manager: MongoDatabaseManager, database_name: str):
    """A stored active template, and one stored without its name; both removed again afterwards"""
    templates = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
    ids: list[int] = [TEMPLATE_ID, NAMELESS_TEMPLATE_ID]

    templates.delete_many({'public_id': {'$in': ids}})
    templates.insert_many([dict(TEMPLATE_PAYLOAD), {'public_id': NAMELESS_TEMPLATE_ID, 'active': True}])

    yield templates

    templates.delete_many({'public_id': {'$in': ids}})


class TestAFailedTemplateRead:
    """The read of the addressed template on update, delete and render"""

    @pytest.mark.parametrize('call', TEMPLATE_READERS, ids=TEMPLATE_READER_IDS)
    def test_a_database_failure_answers_400(self, rest_api, call: Any) -> None:
        """The read's own message, not the generic 500"""
        with patch.object(DocapiTemplatesManager, TEMPLATE_READ_DELEGATE, side_effect=BaseManagerGetError(DB_FAILURE)):
            response = call(rest_api, TEMPLATE_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TEMPLATE_NOT_READABLE_MSG

    @pytest.mark.parametrize('call', TEMPLATE_READERS, ids=TEMPLATE_READER_IDS)
    def test_a_stored_template_without_its_name_answers_400(self, rest_api, call: Any) -> None:
        """Unpatched: the stored document does not fit the model, which is the read's failure too"""
        response = call(rest_api, NAMELESS_TEMPLATE_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == TEMPLATE_NOT_READABLE_MSG

    @pytest.mark.parametrize('call', TEMPLATE_READERS, ids=TEMPLATE_READER_IDS)
    def test_a_programming_error_still_answers_500(self, rest_api, call: Any) -> None:
        """Only the typed read failure is mapped"""
        with patch.object(DocapiTemplatesManager, TEMPLATE_READ_DELEGATE, side_effect=TypeError(BUG)):
            response = call(rest_api, TEMPLATE_ID)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR

    @pytest.mark.parametrize('call', [_put, _delete], ids=['update', 'delete'])
    def test_nothing_is_written_after_a_failed_read(self, rest_api, templates, call: Any) -> None:
        """The write never runs: the stored template is untouched"""
        with patch.object(DocapiTemplatesManager, TEMPLATE_READ_DELEGATE, side_effect=BaseManagerGetError(DB_FAILURE)):
            call(rest_api, TEMPLATE_ID)

        stored: dict[str, Any] = templates.find_one({'public_id': TEMPLATE_ID}, {'_id': 0})
        assert stored == TEMPLATE_PAYLOAD


class TestAFailedObjectRead:
    """The render's read of its object"""

    def test_a_database_failure_answers_400(self, rest_api) -> None:
        """The object read's own message, naming the object"""
        with patch.object(ObjectsManager, 'get_object', side_effect=ObjectsManagerGetError(DB_FAILURE)):
            response = _render(rest_api, TEMPLATE_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == RENDER_OBJECT_NOT_READABLE_MSG.format(object_id=OBJECT_ID)

    def test_a_programming_error_still_answers_500(self, rest_api) -> None:
        """Only the typed read failure is mapped"""
        with patch.object(ObjectsManager, 'get_object', side_effect=TypeError(BUG)):
            response = _render(rest_api, TEMPLATE_ID)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR


def _deleted_after_the_read(templates) -> Any:
    """A get_template that answers the stored template and then lets another request delete it"""
    real_get_template = DocapiTemplatesManager.get_template

    def _read_then_vanish(manager: DocapiTemplatesManager, public_id: int) -> DocapiTemplate | None:
        template: DocapiTemplate | None = real_get_template(manager, public_id)
        templates.delete_many({'public_id': public_id})

        return template

    return _read_then_vanish


class TestATemplateDeletedUnderTheWrite:
    """Another request deletes the template between the route's read and its write"""

    def test_the_update_answers_404_and_writes_nothing(self, rest_api, templates) -> None:
        """No 200 with a template that is not stored, and no upsert bringing it back"""
        with patch.object(DocapiTemplatesManager, 'get_template', _deleted_after_the_read(templates)):
            response = _put(rest_api, TEMPLATE_ID)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == TEMPLATE_MISSING_MSG.format(public_id=TEMPLATE_ID)
        assert templates.count_documents({'public_id': TEMPLATE_ID}) == 0

    def test_the_delete_answers_404(self, rest_api, templates) -> None:
        """Not a 200 ``false`` the frontend reads as success: this request removed nothing"""
        with patch.object(DocapiTemplatesManager, 'get_template', _deleted_after_the_read(templates)):
            response = _delete(rest_api, TEMPLATE_ID)

        assert response.status_code == HTTPStatus.NOT_FOUND
        assert response.get_json()['message'] == TEMPLATE_MISSING_MSG.format(public_id=TEMPLATE_ID)

    @pytest.mark.parametrize('call', [_put, _delete], ids=['update', 'delete'])
    def test_the_control_answers_200(self, rest_api, call: Any) -> None:
        """Without the concurrent delete the same request succeeds"""
        assert call(rest_api, TEMPLATE_ID).status_code == HTTPStatus.OK
