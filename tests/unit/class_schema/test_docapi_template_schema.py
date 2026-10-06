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
Unit tests for cmdb.class_schema.docapi_model.docapi_template_schema

The DocapiTemplate document schema and the two request schemas the write routes derive from it: every key the
frontend's builder sends passes in the shape it sends it, a value of the wrong type is refused naming the key,
the naming rule, the presentation blocks typed only where the renderer reads them, and which keys each write
route purges. A stored template - `to_json` of a model - validates against its own schema
"""
from typing import Any

import pytest
from cerberus import Validator  # type: ignore

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.docapi.docapi_template.docapi_template_constants import (
    TEMPLATE_NAME_BLANK_MSG,
    TEMPLATE_NAME_MAX_LENGTH,
    TEMPLATE_NAME_SEPARATOR_MSG,
    DocapiTemplateKey,
)
from cmdb.interface.rest_api.routes.framework_routes.cmdb_docapi_templates.docapi_template_routes import (
    DOCAPI_TEMPLATE_CREATE_SCHEMA,
    DOCAPI_TEMPLATE_UPDATE_SCHEMA,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 12
NAME: str = 'invoice'


def _frontend_body(**overrides: Any) -> dict[str, Any]:
    """The DocTemplate the frontend's builder sends - every block in its normalised shape"""
    section: dict[str, Any] = {'activated': True, 'content': '<p>{{ root.public_id }}</p>', 'config': {'height': 40}}
    body: dict[str, Any] = {
        'public_id': PUBLIC_ID, 'name': NAME, 'label': 'Invoice', 'author_id': 3, 'active': True,
        'description': '', 'template_data': '<h1>x</h1>', 'template_style': 'body {}', 'template_type': 'DEFAULT',
        'template_parameters': {'type': 7}, 'header': section, 'footer': dict(section),
        'table_of_contents': {'activated': False, 'config': {'pdftoc': {'line-height': 1.2}, 'level0': {}}},
        'cover_page': {'activated': False, 'content': '', 'config': {}},
        'page_config': {'margin': {'margin-top': 10, 'margin-bottom': 10.5, 'margin-left': 8, 'margin-right': 8}},
    }
    body.update(overrides)

    return body


def _errors(schema: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """The errors a schema reports, run as the validate decorator runs it"""
    validator = Validator(schema, purge_unknown=True)
    validator.validate(body)

    return validator.errors


def _document(schema: dict[str, Any], body: dict[str, Any]) -> dict[str, Any]:
    """The document the validate decorator hands the route"""
    validator = Validator(schema, purge_unknown=True)
    assert validator.validate(body), validator.errors

    return validator.document


class TestTheFrontendBody:
    """What the builder sends passes both write schemas"""

    @pytest.mark.parametrize('schema', [DOCAPI_TEMPLATE_CREATE_SCHEMA, DOCAPI_TEMPLATE_UPDATE_SCHEMA],
                             ids=['create', 'update'])
    def test_the_whole_body_passes(self, schema: dict[str, Any]) -> None:
        """Every key in the frontend's shape"""
        assert not _errors(schema, _frontend_body())

    def test_unset_forms_send_null_or_nothing(self) -> None:
        """Every optional key may be null or absent - the model defaults it"""
        nulls = {key.value: None for key in DocapiTemplateKey
                 if key not in (DocapiTemplateKey.PUBLIC_ID, DocapiTemplateKey.NAME)}

        assert not _errors(DOCAPI_TEMPLATE_UPDATE_SCHEMA, {'public_id': PUBLIC_ID, 'name': NAME, **nulls})
        assert not _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, {'name': NAME})

    def test_a_block_keeps_keys_the_schema_does_not_name(self) -> None:
        """The table of contents' styles are not typed, and survive the validation"""
        document = _document(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body())

        assert document['table_of_contents']['config']['pdftoc'] == {'line-height': 1.2}


class TestTheTypes:
    """A value the renderer could not use is refused, naming the key"""

    @pytest.mark.parametrize(('key', 'value'), [
        ('template_data', 5), ('template_style', ['x']), ('label', 3), ('description', {}), ('active', 'yes'),
        ('template_type', 'BOGUS'), ('template_parameters', 'x'), ('template_parameters', {'type': 'seven'}),
        ('header', 'x'), ('footer', {'activated': 'yes'}), ('header', {'config': {'height': 'tall'}}),
        ('cover_page', {'content': 5}), ('table_of_contents', {'activated': 1.5}),
        ('page_config', 'x'), ('page_config', {'margin': {'margin-top': 'wide'}}),
    ])
    def test_a_wrongly_typed_value_is_refused(self, key: str, value: Any) -> None:
        """Each of these used to be stored, and every later render answered 500"""
        assert key in _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body(**{key: value}))

    def test_both_template_types_pass(self) -> None:
        """OBJECT (legacy) and DEFAULT"""
        assert not _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body(template_type='OBJECT'))


class TestTheName:
    """A non-blank string of at most 255 characters without '/'"""

    @pytest.mark.parametrize(('name', 'reason'), [
        ('', TEMPLATE_NAME_BLANK_MSG), ('   ', TEMPLATE_NAME_BLANK_MSG), ('a/b', TEMPLATE_NAME_SEPARATOR_MSG),
    ])
    def test_an_unaddressable_name_is_refused(self, name: str, reason: str) -> None:
        """The by-name route could not reach it"""
        assert _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body(name=name)) == {'name': [reason]}

    @pytest.mark.parametrize('name', [7, None, 'x' * (TEMPLATE_NAME_MAX_LENGTH + 1)])
    def test_a_name_that_is_no_string_or_too_long_is_refused(self, name: Any) -> None:
        """Type and length"""
        assert 'name' in _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body(name=name))

    def test_the_name_is_required(self) -> None:
        """The one key a template must carry"""
        body = _frontend_body()
        del body['name']

        assert 'name' in _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, body)

    @pytest.mark.parametrize('name', ['x' * TEMPLATE_NAME_MAX_LENGTH, 'Rechnung März', 'a.b-c_d'])
    def test_a_usable_name_passes(self, name: str) -> None:
        """Up to the limit, any character but '/'"""
        assert not _errors(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body(name=name))


class TestTheServerOwnedKeys:
    """Which keys each write route takes from the client"""

    def test_create_drops_the_identity_and_the_author(self) -> None:
        """Both are stamped by the route"""
        document = _document(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body())

        assert 'public_id' not in document
        assert 'author_id' not in document

    def test_update_keeps_the_identity_and_drops_the_author(self) -> None:
        """The body's id is the only identity the update route has; the author stays the stored one"""
        document = _document(DOCAPI_TEMPLATE_UPDATE_SCHEMA, _frontend_body())

        assert document['public_id'] == PUBLIC_ID
        assert 'author_id' not in document

    @pytest.mark.parametrize('public_id', [None, 'x', '12'])
    def test_update_needs_an_integer_id(self, public_id: Any) -> None:
        """Missing, null or text: each used to answer 500, or 404 for a template that exists"""
        body = _frontend_body(public_id=public_id)

        if public_id is None:
            del body['public_id']

        assert 'public_id' in _errors(DOCAPI_TEMPLATE_UPDATE_SCHEMA, body)

    def test_an_undeclared_key_is_dropped(self) -> None:
        """The validate decorator purges it before the route sees the body"""
        assert 'inProcess' not in _document(DOCAPI_TEMPLATE_CREATE_SCHEMA, _frontend_body(inProcess=True))


class TestAStoredTemplate:
    """The document the model writes satisfies its own schema"""

    def test_to_json_validates(self) -> None:
        """Built from the frontend's body, defaults filled"""
        template = DocapiTemplate(**_frontend_body())

        assert not _errors(DocapiTemplate.SCHEMA, DocapiTemplate.to_json(template))

    def test_a_minimal_template_validates(self) -> None:
        """Every default the constructor fills in is of its declared type"""
        template = DocapiTemplate(public_id=PUBLIC_ID, name=NAME)

        assert not _errors(DocapiTemplate.SCHEMA, DocapiTemplate.to_json(template))
