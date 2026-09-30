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
What `GET /docapi/template/<id>/render/<object_id>` shows a caller whose group may not read an object

The render reads its object through the caller's READ ACL - a hidden object is a 403, never a PDF -
and so does everything the document pulls in: an object the template names by id renders blank for a
caller who may not read it. What reaches the document is checked on the HTML the template engine
produced, captured before it becomes a PDF, for the admin group (which may read the hidden type) and
for the default user group (which may not)
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.template_engine import TemplateEngine
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID, USER_GROUP_ID
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_OBJECT_DENIED_MSG,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

RENDER_URL: str = '/docapi/template/{template_id}/render/{object_id}'

VISIBLE_TYPE_ID: int = 89101
HIDDEN_TYPE_ID: int = 89102
VISIBLE_ID: int = 89111
HIDDEN_ID: int = 89112
TEMPLATE_ID: int = 89121
USER_ID: int = 89131

NAME_FIELD: str = 'dg_name'
VISIBLE_VALUE: str = 'visible-render-value'
HIDDEN_VALUE: str = 'hidden-render-value'

# The root object's own value, and the hidden object pulled in by its id
TEMPLATE_BODY: str = (
    f'<p>{{{{ root.fields.{NAME_FIELD} }}}}</p>'
    f'<p>{{{{ object({HIDDEN_ID}).fields.{NAME_FIELD} }}}}</p>'
)


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The document generator is licensed, so the render answers its ACL rather than its licence gate."""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='rendered_html')
def fixture_rendered_html(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captures every HTML body the template engine produces, before it is turned into a PDF."""
    captured: list[str] = []
    original = TemplateEngine.render_template_string

    def _capturing(template_str: str, data: dict[str, Any]) -> str:
        html: str = original(template_str, data)
        captured.append(html)
        return html

    monkeypatch.setattr(TemplateEngine, 'render_template_string', staticmethod(_capturing))

    return captured


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """A visible and a hidden object, a DEFAULT template naming the hidden one, and a default-group user."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    templates = database_manager.get_collection(DocapiTemplate.COLLECTION, database_name)
    users = database_manager.get_collection(CmdbUser.COLLECTION, database_name)

    def _purge() -> None:
        types.delete_many({'public_id': {'$in': [VISIBLE_TYPE_ID, HIDDEN_TYPE_ID]}})
        objects.delete_many({'public_id': {'$in': [VISIBLE_ID, HIDDEN_ID]}})
        templates.delete_many({'public_id': TEMPLATE_ID})
        users.delete_many({'public_id': USER_ID})

    _purge()
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}]
    sections: list[dict[str, Any]] = [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}]
    hidden_type: dict[str, Any] = make_type_doc(HIDDEN_TYPE_ID, 'docapi-render-hidden', fields=fields,
                                                sections=sections)
    hidden_type['acl'] = {'activated': True, 'groups': {'includes': {str(ADMIN_GROUP_ID): ['READ']}}}
    types.insert_many([
        make_type_doc(VISIBLE_TYPE_ID, 'docapi-render-visible', fields=fields, sections=sections), hidden_type,
    ])
    now: datetime = datetime.now(timezone.utc)
    objects.insert_many([
        {'public_id': object_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
         'creation_time': now, 'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': value}]}
        for object_id, type_id, value in [(VISIBLE_ID, VISIBLE_TYPE_ID, VISIBLE_VALUE),
                                          (HIDDEN_ID, HIDDEN_TYPE_ID, HIDDEN_VALUE)]
    ])
    templates.insert_one({
        'public_id': TEMPLATE_ID, 'name': 'tpl-render-acl', 'label': 'Render ACL', 'active': True,
        'author_id': 1, 'template_type': DocapiTemplateType.DEFAULT.value, 'template_data': TEMPLATE_BODY,
        'template_style': '',
    })
    users.insert_one({'public_id': USER_ID, 'user_name': 'docapi-render-acl', 'active': True,
                      'group_id': USER_GROUP_ID, 'registration_time': now})
    yield
    _purge()


def _default_user() -> CmdbUser:
    """The seeded member of the default 'user' group - holds object view, may not read the hidden type."""
    return CmdbUser(public_id=USER_ID, user_name='docapi-render-acl', active=True, group_id=USER_GROUP_ID)


def _render(rest_api, object_id: int, **kwargs: Any):
    """Renders the template for `object_id`."""
    return rest_api.get(RENDER_URL.format(template_id=TEMPLATE_ID, object_id=object_id), **kwargs)


class TestTheRootObject:
    """The object the render is asked for."""

    def test_a_hidden_object_is_a_403(self, rest_api) -> None:
        """Read through the caller's ACL, like GET /objects/<id> - never rendered"""
        response = _render(rest_api, HIDDEN_ID, user=_default_user())

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert response.get_json()['message'] == RENDER_OBJECT_DENIED_MSG.format(object_id=HIDDEN_ID)

    def test_a_caller_who_may_read_it_gets_the_pdf(self, rest_api) -> None:
        """The admin group may read the hidden type"""
        assert _render(rest_api, HIDDEN_ID).status_code == HTTPStatus.OK


class TestWhatTheDocumentPullsIn:
    """An object the template names by id."""

    def test_the_admin_sees_it(self, rest_api, rendered_html: list[str]) -> None:
        """The control: the template reaches the hidden object's value for a reader of its type"""
        assert _render(rest_api, VISIBLE_ID).status_code == HTTPStatus.OK
        assert HIDDEN_VALUE in rendered_html[-1]
        assert VISIBLE_VALUE in rendered_html[-1]

    def test_the_default_user_does_not(self, rest_api, rendered_html: list[str]) -> None:
        """The document renders, with the hidden object blank - its value is nowhere in it"""
        assert _render(rest_api, VISIBLE_ID, user=_default_user()).status_code == HTTPStatus.OK
        assert VISIBLE_VALUE in rendered_html[-1]
        assert HIDDEN_VALUE not in rendered_html[-1]
