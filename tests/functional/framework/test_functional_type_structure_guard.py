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
A CmdbType's sections and summary line may only show fields the Type declares

The reproduction of the "copy a type creates broken type" report, turned into regression tests. A
Type declares every field once in its flat ``fields`` list; its sections and its
``render_meta.summary`` carry only the NAMES. A payload that rewrites the field identifiers without
rewriting the section reference lists used to be stored as sent, and produced a Type that:

  * rendered **none** of its fields - every section pointed at names that no longer existed
  * still held those fields, so adding one under the intended name was refused as a duplicate

The summary line breaks the same way from the other side: a name that resolves to nothing is skipped
by the renderer, so the entry vanishes from the one line every list, picker and reference identifies
an Object by, and the Object reads as if it simply had no value there.

Both write routes are covered because both write the whole document. The type import already
enforced the same rules (``validate_type_structure``); these close the gap for the routes the UI
uses.
"""
import uuid
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.models.type_model.cmdb_type import CmdbType
from cmdb.database.mongo_database_manager import MongoDatabaseManager
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/types/'

FIELD_A: str = 'text-a'
FIELD_B: str = 'text-b'
SECTION_A: str = 'section-a'

# Every Type these tests create is named with this prefix, so the cleanup can find them all without
# each test having to report the ids it produced
TYPE_NAME_PREFIX: str = 'structure_guard_'


@pytest.fixture(autouse=True)
def drop_created_types(database_manager: MongoDatabaseManager, database_name: str):
    """Removes every Type these tests created

    The accepted cases here write real Types, and `/types/` answers one page - so leaving them behind
    pushes the Types other functional tests read off the first page of their own list responses.
    """
    yield

    database_manager.get_collection(CmdbType.COLLECTION, database_name).delete_many(
        {'name': {'$regex': f'^{TYPE_NAME_PREFIX}'}}
    )


def _field(name: str, label: str = 'Label') -> dict[str, Any]:
    """The minimal field definition the schema accepts."""
    return {'type': 'text', 'name': name, 'label': label}


def _payload(
    fields: list[dict[str, Any]],
    sections: list[dict[str, Any]],
    summary: list[str] | None = None,
) -> dict[str, Any]:
    """A schema-valid Type payload carrying the given structure."""
    return {
        'author_id': 1,
        'name': f'{TYPE_NAME_PREFIX}{uuid.uuid4().hex[:10]}',
        'label': 'Structure Guard',
        'active': True,
        'fields': fields,
        'render_meta': {
            'icon': 'fa fa-cube',
            'sections': sections,
            'externals': [],
            'summary': {'fields': summary or []},
        },
    }


def _section(name: str, fields: list[str]) -> dict[str, Any]:
    """A plain section referencing the given field names."""
    return {'type': 'section', 'name': name, 'label': 'Section', 'fields': fields}


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    POST /types/                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateRefusesAnInconsistentType:
    """The shape a copied Type with renamed identifiers arrives in."""

    def test_a_section_naming_an_undeclared_field_is_refused(self, rest_api) -> None:
        """The reported bug - this answered 201 and stored an unusable Type"""
        response = rest_api.post(
            ROUTE_URL, json=_payload([_field(FIELD_A)], [_section(SECTION_A, ['text-old'])]),
        )

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'text-old' in response.get_json()['message']

    def test_the_whole_copy_shape_is_refused(self, rest_api) -> None:
        """Every field renamed, every section reference left behind: nothing would render"""
        payload = _payload(
            [_field('text-new-1'), _field('text-new-2')],
            [_section(SECTION_A, ['text-old-1', 'text-old-2'])],
        )

        assert rest_api.post(ROUTE_URL, json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_field_identifiers_are_refused(self, rest_api) -> None:
        """Two fields under one name - an Object keys its values by the name alone"""
        payload = _payload(
            [_field(FIELD_A, 'First'), _field(FIELD_A, 'Second')], [_section(SECTION_A, [FIELD_A])],
        )

        assert rest_api.post(ROUTE_URL, json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_duplicate_section_identifiers_are_refused(self, rest_api) -> None:
        """Section names are what MDS propagation matches on"""
        payload = _payload(
            [_field(FIELD_A)], [_section(SECTION_A, [FIELD_A]), _section(SECTION_A, [])],
        )

        assert rest_api.post(ROUTE_URL, json=payload).status_code == HTTPStatus.BAD_REQUEST

    def test_a_summary_naming_an_undeclared_field_is_refused(self, rest_api) -> None:
        """The summary entry would be skipped by the renderer and the line would show nothing"""
        payload = _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=['text-old'])
        response = rest_api.post(ROUTE_URL, json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'text-old' in response.get_json()['message']

    def test_a_summary_naming_one_field_twice_is_refused(self, rest_api) -> None:
        """The repeat renders the same value twice, as if two fields held it"""
        payload = _payload(
            [_field(FIELD_A), _field(FIELD_B)],
            [_section(SECTION_A, [FIELD_A, FIELD_B])],
            summary=[FIELD_A, FIELD_B, FIELD_A],
        )
        response = rest_api.post(ROUTE_URL, json=payload)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert FIELD_A in response.get_json()['message']

    def test_a_summary_naming_a_declared_field_is_still_created(self, rest_api) -> None:
        """The ordinary configured summary line"""
        payload = _payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])], summary=[FIELD_A])

        assert rest_api.post(ROUTE_URL, json=payload).status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_consistent_type_is_still_created(self, rest_api) -> None:
        """The guard may not cost the ordinary case"""
        payload = _payload(
            [_field(FIELD_A), _field(FIELD_B)], [_section(SECTION_A, [FIELD_A, FIELD_B])],
        )
        response = rest_api.post(ROUTE_URL, json=payload)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

    def test_a_field_no_section_shows_is_still_created(self, rest_api) -> None:
        """A Type under construction legitimately carries one"""
        response = rest_api.post(ROUTE_URL, json=_payload([_field(FIELD_A)], [_section(SECTION_A, [])]))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 PUT /types/<id>                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateRefusesAnInconsistentType:
    """An update writes the whole document, so it can introduce the same state."""

    @pytest.fixture(name='stored_type')
    def fixture_stored_type(self, rest_api):
        """A consistent Type, read back exactly as the builder would load it."""
        created = rest_api.post(
            ROUTE_URL, json=_payload([_field(FIELD_A)], [_section(SECTION_A, [FIELD_A])]),
        )
        assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        return created.get_json()['raw']

    def test_renaming_a_field_without_its_reference_is_refused(self, rest_api, stored_type) -> None:
        """This answered 202 and left the Type rendering 0 of 1 fields"""
        stored_type['fields'] = [_field('text-renamed')]

        response = rest_api.put(f"{ROUTE_URL}{stored_type['public_id']}", json=stored_type)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert FIELD_A in response.get_json()['message']

    def test_the_stored_type_is_left_untouched(self, rest_api, stored_type) -> None:
        """A refused update may not have written half of itself"""
        stored_type['fields'] = [_field('text-renamed')]
        rest_api.put(f"{ROUTE_URL}{stored_type['public_id']}", json=stored_type)

        reread = rest_api.get(f"{ROUTE_URL}{stored_type['public_id']}").get_json()['result']

        assert [field['name'] for field in reread['fields']] == [FIELD_A]

    def test_renaming_both_halves_together_is_accepted(self, rest_api, stored_type) -> None:
        """The fix for the refused update: rewrite the section reference too"""
        stored_type['fields'] = [_field('text-renamed')]
        stored_type['render_meta']['sections'] = [_section(SECTION_A, ['text-renamed'])]

        response = rest_api.put(f"{ROUTE_URL}{stored_type['public_id']}", json=stored_type)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)


# -------------------------------------------------------------------------------------------------------------------- #
#                                        PUT /types/<id> - the summary line                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestUpdateRefusesAnInconsistentSummary:
    """Dropping a field the summary line still names is the way an update breaks the summary."""

    @pytest.fixture(name='summary_type')
    def fixture_summary_type(self, rest_api):
        """A Type whose summary line shows one of its two fields."""
        created = rest_api.post(
            ROUTE_URL,
            json=_payload(
                [_field(FIELD_A), _field(FIELD_B)],
                [_section(SECTION_A, [FIELD_A, FIELD_B])],
                summary=[FIELD_B],
            ),
        )
        assert created.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        return created.get_json()['raw']

    def test_dropping_a_field_the_summary_still_names_is_refused(self, rest_api, summary_type) -> None:
        """This answered 202 and left the summary line one entry shorter than configured"""
        summary_type['fields'] = [_field(FIELD_A)]
        summary_type['render_meta']['sections'] = [_section(SECTION_A, [FIELD_A])]

        response = rest_api.put(f"{ROUTE_URL}{summary_type['public_id']}", json=summary_type)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert FIELD_B in response.get_json()['message']

    def test_the_stored_summary_is_left_untouched(self, rest_api, summary_type) -> None:
        """A refused update may not have written half of itself"""
        summary_type['fields'] = [_field(FIELD_A)]
        summary_type['render_meta']['sections'] = [_section(SECTION_A, [FIELD_A])]
        rest_api.put(f"{ROUTE_URL}{summary_type['public_id']}", json=summary_type)

        reread = rest_api.get(f"{ROUTE_URL}{summary_type['public_id']}").get_json()['result']

        assert reread['render_meta']['summary']['fields'] == [FIELD_B]

    def test_repeating_a_summary_entry_is_refused(self, rest_api, summary_type) -> None:
        """An update writes the whole summary, so it can introduce the repeat too"""
        summary_type['render_meta']['summary']['fields'] = [FIELD_A, FIELD_B, FIELD_A]

        response = rest_api.put(f"{ROUTE_URL}{summary_type['public_id']}", json=summary_type)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert FIELD_A in response.get_json()['message']

    def test_naming_both_fields_once_is_accepted(self, rest_api, summary_type) -> None:
        """Extending the line with the Type's other field is the ordinary edit"""
        summary_type['render_meta']['summary']['fields'] = [FIELD_A, FIELD_B]

        response = rest_api.put(f"{ROUTE_URL}{summary_type['public_id']}", json=summary_type)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)

    def test_dropping_the_field_and_its_summary_entry_is_accepted(self, rest_api, summary_type) -> None:
        """The fix for the refused update: take the name out of the summary line too"""
        summary_type['fields'] = [_field(FIELD_A)]
        summary_type['render_meta']['sections'] = [_section(SECTION_A, [FIELD_A])]
        summary_type['render_meta']['summary']['fields'] = []

        response = rest_api.put(f"{ROUTE_URL}{summary_type['public_id']}", json=summary_type)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
