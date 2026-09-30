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
What a CmdbSectionTemplate write accepts, and what it stores

The write routes validate no request schema, and none is available as-is: the payload arrives as
query parameters with ``fields`` JSON-encoded, while ``CmdbSectionTemplate.SCHEMA`` describes the
document. Nothing below the route consults that schema either - the manager builds the model and
inserts its ``__dict__`` - so the route helpers are the only validation there is. This pins them.

Two of the rules exist because of what happens *after* the write:

* a template's **fields are inlined into every consuming CmdbType**, so a field entry that could not
  be a type field becomes an unusable field on all of them, past the type write routes where such a
  shape would otherwise be refused
* a template's **name is the propagation key** consuming types reference it by, and it is immutable
  once stored - so a blank one can never be repaired, only deleted

The third is about what the document holds: the model takes ``**kwargs``, so any extra request
parameter would become a stored key the schema does not declare - and ``to_json`` drops it on read,
making it invisible to every reader while surviving each later edit.
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.section_template_model.cmdb_section_template import CmdbSectionTemplate
from cmdb.models.section_template_model.section_template_constants import (
    SECTION_TEMPLATE_TEXT_MAX_LENGTH,
    SectionTemplateKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/section_templates'

NAME_PREFIX: str = 'write-contract-'
TEMPLATE_LABEL: str = 'Write Contract'

USABLE_FIELDS: str = (
    '[{"name": "text-a", "label": "Text A", "type": "text"}]'
)


@pytest.fixture(name='templates', autouse=True)
def fixture_templates(database_manager: MongoDatabaseManager, database_name: str):
    """The template collection, cleared of this file's templates around each test."""
    collection = database_manager.get_collection(CmdbSectionTemplate.COLLECTION, database_name)

    def _purge() -> None:
        collection.delete_many({SectionTemplateKey.NAME.value: {'$regex': f'^{NAME_PREFIX}'}})

    _purge()

    yield collection

    _purge()


def _params(name: str = f'{NAME_PREFIX}one', **overrides: Any) -> dict[str, Any]:
    """The query-string payload a create parses; every value is text and `fields` is JSON."""
    params: dict[str, Any] = {
        SectionTemplateKey.NAME.value: name,
        SectionTemplateKey.LABEL.value: TEMPLATE_LABEL,
        SectionTemplateKey.TYPE.value: SectionType.SECTION.value,
        SectionTemplateKey.IS_GLOBAL.value: 'false',
        SectionTemplateKey.PREDEFINED.value: 'false',
        SectionTemplateKey.FIELDS.value: USABLE_FIELDS,
    }
    params.update(overrides)

    return params


def _create(rest_api, **overrides: Any):
    """POSTs a template."""
    return rest_api.post(f'{ROUTE_URL}/', query_string=_params(**overrides))


def _stored(templates, public_id: int) -> dict[str, Any]:
    """The written document."""
    return templates.find_one({SectionTemplateKey.PUBLIC_ID.value: public_id}) or {}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            ONLY THE WRITE KEYS ARE STORED                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestOnlyTheWriteKeysAreStored:
    """The model takes **kwargs, so an extra parameter would otherwise become a document key."""

    def test_an_unknown_parameter_is_not_stored(self, rest_api, templates) -> None:
        """It was invisible on read and survived every later edit"""
        response = _create(rest_api, injected='value')

        assert response.status_code == HTTPStatus.OK
        assert 'injected' not in _stored(templates, response.get_json())

    def test_the_stored_document_holds_only_declared_keys(self, rest_api, templates) -> None:
        """Every key of the document is one the schema declares"""
        document = _stored(templates, _create(rest_api).get_json())
        declared = {key.value for key in SectionTemplateKey} | {'_id'}

        assert set(document).issubset(declared)

    def test_an_unknown_parameter_is_not_stored_by_an_update(self, rest_api, templates) -> None:
        """Both write routes drop it, so neither can reintroduce what the other refuses"""
        public_id = _create(rest_api).get_json()

        rest_api.put(f'{ROUTE_URL}/', query_string=_params(public_id=str(public_id), injected='value'))

        assert 'injected' not in _stored(templates, public_id)

    def test_the_public_id_is_still_server_assigned(self, rest_api, templates) -> None:
        """It is a write key, so the allow-list keeps it - the route overwrites it regardless"""
        response = _create(rest_api, public_id='4242')

        assert response.get_json() != 4242
        assert not templates.count_documents({SectionTemplateKey.PUBLIC_ID.value: 4242})


# -------------------------------------------------------------------------------------------------------------------- #
#                                               NAME AND LABEL ARE TEXT                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheNameAndLabelMustBeUsable:
    """Both are rendered, and the name is the immutable propagation key."""

    @pytest.mark.parametrize('name', ['', '   '], ids=repr)
    def test_a_blank_name_is_refused(self, rest_api, name: str) -> None:
        """Stored, it could never be repaired - the update route refuses to rename"""
        response = _create(rest_api, name=name)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert SectionTemplateKey.NAME.value in response.get_json()['message']

    @pytest.mark.parametrize('label', ['', '   '], ids=repr)
    def test_a_blank_label_is_refused(self, rest_api, label: str) -> None:
        """The label heads the section on every consuming type's form"""
        response = _create(rest_api, label=label)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert SectionTemplateKey.LABEL.value in response.get_json()['message']

    def test_a_name_over_the_cap_is_refused(self, rest_api) -> None:
        """A name no UI can render must not become a propagation key"""
        response = _create(rest_api, name=NAME_PREFIX + 'x' * SECTION_TEMPLATE_TEXT_MAX_LENGTH)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_name_at_the_cap_is_accepted(self, rest_api) -> None:
        """The boundary belongs to the caller"""
        name = (NAME_PREFIX + 'x' * SECTION_TEMPLATE_TEXT_MAX_LENGTH)[:SECTION_TEMPLATE_TEXT_MAX_LENGTH]

        assert _create(rest_api, name=name).status_code == HTTPStatus.OK

    def test_an_update_refuses_a_blank_label(self, rest_api, templates) -> None:
        """The update route judges the same values by the same rules"""
        public_id = _create(rest_api).get_json()

        response = rest_api.put(
            f'{ROUTE_URL}/', query_string=_params(public_id=str(public_id), label=''),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(templates, public_id)[SectionTemplateKey.LABEL.value] == TEMPLATE_LABEL


# -------------------------------------------------------------------------------------------------------------------- #
#                                          A FIELD HAS TO BE A USABLE FIELD                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheFieldsMustBeUsable:
    """They are inlined into every consuming CmdbType, past the type write routes."""

    @pytest.mark.parametrize('fields', [
        '[{}]',
        '[{"label": "L", "type": "text"}]',
        '[{"name": "  ", "label": "L", "type": "text"}]',
    ], ids=['empty object', 'no name', 'blank name'])
    def test_a_field_without_a_name_is_refused(self, rest_api, fields: str) -> None:
        """The name is the field's identifier, and an Object keys its stored value by it"""
        response = _create(rest_api, fields=fields)

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_field_without_a_label_is_refused(self, rest_api) -> None:
        """It is what the field is rendered as, on every consuming type"""
        response = _create(rest_api, fields='[{"name": "text-a", "type": "text"}]')

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'text-a' in response.get_json()['message']

    def test_an_unknown_field_type_is_refused(self, rest_api) -> None:
        """The same rule the type import applies to an uploaded field"""
        response = _create(rest_api, fields='[{"name": "text-a", "label": "L", "type": "nonsense"}]')

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_a_duplicate_field_name_is_refused(self, rest_api) -> None:
        """The type they are inlined into would be refused for it by the type structure guard"""
        response = _create(rest_api, fields=(
            '[{"name": "text-a", "label": "A", "type": "text"},'
            ' {"name": "text-a", "label": "B", "type": "text"}]'
        ))

        assert response.status_code == HTTPStatus.BAD_REQUEST

    def test_an_update_refuses_the_same_shapes(self, rest_api, templates) -> None:
        """And leaves the stored fields alone"""
        public_id = _create(rest_api).get_json()

        response = rest_api.put(
            f'{ROUTE_URL}/', query_string=_params(public_id=str(public_id), fields='[{}]'),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(templates, public_id)[SectionTemplateKey.FIELDS.value][0][
            FieldKey.NAME.value
        ] == 'text-a'

    def test_an_empty_field_list_is_still_accepted(self, rest_api) -> None:
        """A template under construction has no fields yet"""
        assert _create(rest_api, fields='[]').status_code == HTTPStatus.OK

    @pytest.mark.parametrize('field_type', [kind.value for kind in FieldType])
    def test_every_known_field_type_is_still_accepted(self, rest_api, field_type: str) -> None:
        """The guard may not narrow what a section can hold"""
        response = _create(
            rest_api,
            name=f'{NAME_PREFIX}{field_type}',
            fields=f'[{{"name": "f", "label": "F", "type": "{field_type}"}}]',
        )

        assert response.status_code == HTTPStatus.OK


# -------------------------------------------------------------------------------------------------------------------- #
#                                            WHAT THE GUARDS MAY NOT COST                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheOrdinaryWriteStillWorks:
    """The guards may not cost a legitimate template."""

    def test_a_template_is_created_and_read_back(self, rest_api, templates) -> None:
        """The whole ordinary path"""
        response = _create(rest_api)
        document = _stored(templates, response.get_json())

        assert response.status_code == HTTPStatus.OK
        assert document[SectionTemplateKey.NAME.value] == f'{NAME_PREFIX}one'
        assert document[SectionTemplateKey.FIELDS.value][0][FieldKey.NAME.value] == 'text-a'

    def test_a_multi_data_section_template_is_created(self, rest_api) -> None:
        """The second of the two section kinds a template may declare"""
        response = _create(rest_api, type=SectionType.MDS_SECTION.value)

        assert response.status_code == HTTPStatus.OK

    def test_an_update_writes_the_new_label(self, rest_api, templates) -> None:
        """And the route still answers 202"""
        public_id = _create(rest_api).get_json()

        response = rest_api.put(
            f'{ROUTE_URL}/', query_string=_params(public_id=str(public_id), label='Renamed Label'),
        )

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        assert _stored(templates, public_id)[SectionTemplateKey.LABEL.value] == 'Renamed Label'
