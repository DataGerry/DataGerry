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
Functional coverage for what the DocAPI render route requires before it renders

  - both rights: `base.framework.object.view` for the object and `base.docapi.template.view` for the template
    the document reproduces - a group holding either alone is refused, a group holding both passes the gate
  - the route asks `.protect` for exactly those two rights, object first
  - a deactivated template is refused with a 400 naming it, and only the render refuses: the template is
    still read and still listed by the picker's searchfilter
  - the template is not checked against the object's type: a template bound to another type renders, its
    fields blank
"""
import re
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.docapi_model.docapi_template_type_enum import DocapiTemplateType
from cmdb.models.docapi_model.template_engine import TemplateEngine
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.right_model.right_constants import ObjectRightName
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_constants import (
    RENDER_TEMPLATE_DEACTIVATED_MSG,
    DocapiTemplateRight,
)
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

API_BLUEPRINT_PATH: str = 'cmdb.interface.blueprints.api_blueprint.user_has_right'
RENDER_URL: str = '/docapi/template/{template_id}/render/{object_id}'
CRUD_URL: str = '/docapi/template'

TYPE_ID: int = 89301
OTHER_TYPE_ID: int = 89302
OBJECT_ID: int = 89311
ACTIVE_TEMPLATE_ID: int = 89321
DEACTIVATED_TEMPLATE_ID: int = 89322
OTHER_TYPE_TEMPLATE_ID: int = 89323
MISSING_TEMPLATE_ID: int = 89399
TEMPLATE_IDS: list[int] = [ACTIVE_TEMPLATE_ID, DEACTIVATED_TEMPLATE_ID, OTHER_TYPE_TEMPLATE_ID]

NAME_FIELD: str = 'dg_name'
OTHER_FIELD: str = 'dg_other'
OBJECT_VALUE: str = 'render-rights-value'

# One group per combination of the two rights, one member each: (group id, user id, rights)
OBJECT_ONLY: tuple[int, int, list[str]] = (89331, 89341, [ObjectRightName.VIEW.value])
TEMPLATE_ONLY: tuple[int, int, list[str]] = (89332, 89342, [DocapiTemplateRight.VIEW.value])
BOTH: tuple[int, int, list[str]] = (89333, 89343, [ObjectRightName.VIEW.value, DocapiTemplateRight.VIEW.value])
ALL_TEMPLATE_RIGHTS: tuple[int, int, list[str]] = (89334, 89344, [right.value for right in DocapiTemplateRight])
GROUPS: list[tuple[int, int, list[str]]] = [OBJECT_ONLY, TEMPLATE_ONLY, BOTH, ALL_TEMPLATE_RIGHTS]


@pytest.fixture(autouse=True)
def _licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """The document generator is licensed, so the render answers its rights rather than its licence gate"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, _feature: True)


@pytest.fixture(name='rendered_html')
def fixture_rendered_html(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Captures every HTML body the template engine produces, before it is turned into a PDF"""
    captured: list[str] = []
    original = TemplateEngine.render_template_string

    def _capturing(template_str: str, data: dict[str, Any]) -> str:
        html: str = original(template_str, data)
        captured.append(html)
        return html

    monkeypatch.setattr(TemplateEngine, 'render_template_string', staticmethod(_capturing))

    return captured


def _template(public_id: int, active: bool, type_id: int, field: str) -> dict[str, Any]:
    """A template bound to `type_id`, printing `field` of the root object"""
    return {
        'public_id': public_id, 'name': f'tpl-render-rights-{public_id}', 'label': 'Render rights', 'active': active,
        'author_id': 1, 'template_type': DocapiTemplateType.DEFAULT.value,
        'template_parameters': {'type': type_id},
        'template_data': f'<p>[{{{{ root.fields.{field} }}}}]</p>', 'template_style': '',
    }


@pytest.fixture(autouse=True)
def _seed(database_manager: MongoDatabaseManager, database_name: str):
    """A type with one object, three templates and one group + member per combination of rights"""
    collections = {model: database_manager.get_collection(model.COLLECTION, database_name)
                   for model in (CmdbType, CmdbObject, DocapiTemplate, CmdbUserGroup, CmdbUser)}

    def _purge() -> None:
        collections[CmdbType].delete_many({'public_id': {'$in': [TYPE_ID, OTHER_TYPE_ID]}})
        collections[CmdbObject].delete_many({'public_id': OBJECT_ID})
        collections[DocapiTemplate].delete_many({'public_id': {'$in': TEMPLATE_IDS}})
        collections[CmdbUserGroup].delete_many({'public_id': {'$in': [group[0] for group in GROUPS]}})
        collections[CmdbUser].delete_many({'public_id': {'$in': [group[1] for group in GROUPS]}})

    _purge()
    now: datetime = datetime.now(timezone.utc)
    fields: list[dict[str, Any]] = [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}]
    sections: list[dict[str, Any]] = [{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [NAME_FIELD]}]
    collections[CmdbType].insert_many([
        make_type_doc(TYPE_ID, 'docapi-render-rights', fields=fields, sections=sections),
        make_type_doc(OTHER_TYPE_ID, 'docapi-render-rights-other',
                      fields=[{'type': 'text', 'name': OTHER_FIELD, 'label': 'Other'}],
                      sections=[{'type': 'section', 'name': 'main', 'label': 'Main', 'fields': [OTHER_FIELD]}]),
    ])
    collections[CmdbObject].insert_one({
        'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1, 'version': '1.0.0',
        'creation_time': now, 'fields': [{'type': 'text', 'name': NAME_FIELD, 'value': OBJECT_VALUE}],
    })
    collections[DocapiTemplate].insert_many([
        _template(ACTIVE_TEMPLATE_ID, True, TYPE_ID, NAME_FIELD),
        _template(DEACTIVATED_TEMPLATE_ID, False, TYPE_ID, NAME_FIELD),
        _template(OTHER_TYPE_TEMPLATE_ID, True, OTHER_TYPE_ID, OTHER_FIELD),
    ])
    for group_id, user_id, rights in GROUPS:
        collections[CmdbUserGroup].insert_one({'public_id': group_id, 'name': f'render-rights-{group_id}',
                                               'label': f'Render rights {group_id}', 'rights': rights})
        collections[CmdbUser].insert_one({'public_id': user_id, 'user_name': f'render-rights-{user_id}',
                                          'active': True, 'group_id': group_id, 'registration_time': now})
    yield
    _purge()


def _member(group: tuple[int, int, list[str]]) -> CmdbUser:
    """The seeded member of one of the rights groups"""
    group_id, user_id, _ = group

    return CmdbUser(public_id=user_id, user_name=f'render-rights-{user_id}', active=True, group_id=group_id)


def _render(rest_api, template_id: int, **kwargs: Any):
    """Renders `template_id` for the seeded object"""
    return rest_api.get(RENDER_URL.format(template_id=template_id, object_id=OBJECT_ID), **kwargs)


class TestTheTwoRights:
    """A render needs the object right AND the template right"""

    @pytest.mark.parametrize('group', [OBJECT_ONLY, TEMPLATE_ONLY, ALL_TEMPLATE_RIGHTS],
                             ids=['object-view-only', 'template-view-only', 'all-template-rights'])
    def test_either_right_alone_is_refused(self, rest_api, group) -> None:
        """object.view alone used to render any template; the template rights alone never did"""
        assert _render(rest_api, ACTIVE_TEMPLATE_ID, user=_member(group)).status_code == HTTPStatus.FORBIDDEN

    def test_both_rights_pass_the_gate(self, rest_api, rendered_html: list[str]) -> None:
        """The pair is enough - the document carries the object's value"""
        response = _render(rest_api, ACTIVE_TEMPLATE_ID, user=_member(BOTH))

        assert response.status_code == HTTPStatus.OK
        assert f'[{OBJECT_VALUE}]' in rendered_html[0]

    def test_the_gate_runs_before_the_template_is_looked_up(self, rest_api) -> None:
        """A caller without the template right learns nothing about which template ids exist"""
        assert _render(rest_api, MISSING_TEMPLATE_ID, user=_member(OBJECT_ONLY)).status_code == HTTPStatus.FORBIDDEN
        assert _render(rest_api, MISSING_TEMPLATE_ID, user=_member(BOTH)).status_code == HTTPStatus.NOT_FOUND

    def test_the_route_asks_for_exactly_the_two_rights(self, rest_api, monkeypatch: pytest.MonkeyPatch) -> None:
        """Object right first, then the template right"""
        asked: list[str] = []

        def _record(right: str, user: Any = None) -> bool:
            del user
            asked.append(right)
            return True

        monkeypatch.setattr(API_BLUEPRINT_PATH, _record)

        _render(rest_api, MISSING_TEMPLATE_ID)

        assert asked == [ObjectRightName.VIEW.value, DocapiTemplateRight.VIEW.value]


class TestADeactivatedTemplate:
    """`active` off: the render refuses, everything else still sees the template"""

    def test_the_render_answers_400_naming_the_template(self, rest_api, rendered_html: list[str]) -> None:
        """It used to render as if active"""
        response = _render(rest_api, DEACTIVATED_TEMPLATE_ID)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == RENDER_TEMPLATE_DEACTIVATED_MSG.format(
            public_id=DEACTIVATED_TEMPLATE_ID)
        assert not rendered_html

    def test_the_template_is_still_read_and_listed(self, rest_api) -> None:
        """The builder and the picker keep showing it - only the render refuses"""
        assert rest_api.get(f'{CRUD_URL}/{DEACTIVATED_TEMPLATE_ID}').status_code == HTTPStatus.OK

        listed = rest_api.get(f'{CRUD_URL}/by/{{"template_parameters": {{"type": {TYPE_ID}}}}}?minimal=true')

        assert DEACTIVATED_TEMPLATE_ID in [entry['public_id'] for entry in listed.get_json()]

    def test_an_active_template_renders(self, rest_api, rendered_html: list[str]) -> None:
        """The check is on the flag, not on every template"""
        assert _render(rest_api, ACTIVE_TEMPLATE_ID).status_code == HTTPStatus.OK
        assert rendered_html


class TestTheTypeIsNotChecked:
    """A template bound to another type still renders"""

    def test_a_template_of_another_type_renders_its_fields_blank(self, rest_api, rendered_html: list[str]) -> None:
        """The object carries no field of that type: blank, not refused"""
        response = _render(rest_api, OTHER_TYPE_TEMPLATE_ID)

        assert response.status_code == HTTPStatus.OK
        # A blank cell renders as a non-breaking space, which \s matches
        assert re.search(r'\[\s*\]', rendered_html[0])
