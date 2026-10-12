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
Functional tests for persons and person groups - CmdbObjects of the PERSON / PERSON_GROUP SpecialTypes - over HTTP

The types are created the way the special-type creation dialog does it (GET /special_types/schema, POST /types/)
and WITHOUT a license - persons are a standard feature. The persons, the group and an asset selecting them are
written through POST /objects/, so the person field enforcement of the object write path runs. Covered:

  - the object write path: a valid selection is stored canonically with its row type; an unknown id, a wrong kind
    and a bad shape are refused with 400 and store nothing
  - GET /person_relations/types, /candidates, /<id> - memberships, members and assignments
  - POST /person_relations/<group>/members and DELETE .../members/<person>, incl. the 400 / 404 answers
  - the read-only legacy GET /persons and /person_groups the ISMS module reads (ISMS-licensed)
  - deleting a person removes it from the group's members and from the asset's person field
  - the CI Explorer grafts the person neighbours in
"""
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.person_constants import PersonField, PersonGroupField
from cmdb.models.type_model import CmdbType
from cmdb.security.license.license_constants import LicenseFeature
from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

RELATIONS_URL: str = '/person_relations'
NAME_PREFIX: str = 'person-relations-'

ASSET_TYPE_ID: int = 96501
ADA_ID: int = 96511
BOB_ID: int = 96512
CAROL_ID: int = 96513
GROUP_ID: int = 96521
EMPTY_GROUP_ID: int = 96522
ASSET_ID: int = 96531
REFUSED_ID: int = 96539
ALL_OBJECT_IDS: list[int] = [ADA_ID, BOB_ID, CAROL_ID, GROUP_ID, EMPTY_GROUP_ID, ASSET_ID, REFUSED_ID]
UNKNOWN_ID: int = 96599

OWNER_FIELD: str = 'pr-owner'
TEAM_FIELD: str = 'pr-team'
MEMBERS: str = PersonGroupField.MEMBERS.value


def _sel(ref_type: str, object_id: Any) -> dict[str, Any]:
    return {'ref_type': ref_type, 'id': object_id}


def _purge(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Every person / group type and its objects, the asset type and this module's objects"""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    person_type_ids = [doc['public_id'] for doc in types.find({'special_type': {'$in': ['PERSON', 'PERSON_GROUP']}})]

    objects.delete_many({'$or': [{'public_id': {'$in': ALL_OBJECT_IDS}},
                                 {'type_id': {'$in': person_type_ids + [ASSET_TYPE_ID]}}]})
    types.delete_many({'public_id': {'$in': person_type_ids + [ASSET_TYPE_ID]}})


def _create_special_type(rest_api, special_type: str) -> int:
    """GET the blueprint, POST it as a type - what the creation dialog does"""
    schema = rest_api.get(f'/special_types/schema?special_type={special_type}').get_json()
    names = [field['name'] for field in schema['fields']]
    payload = {
        'name': f'{NAME_PREFIX}{special_type.lower()}',
        'label': special_type.title(),
        'author_id': 1,
        'active': True,
        'special_type': special_type,
        'fields': schema['fields'],
        'render_meta': {'icon': 'fas fa-user', 'sections': schema['sections'], 'summary': {'fields': names[:1]}},
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }
    response = rest_api.post('/types/', json=payload)

    assert response.status_code == HTTPStatus.CREATED, response.get_json()

    return rest_api.get(f'{RELATIONS_URL}/types').get_json()[special_type]


def _post_object(rest_api, public_id: int, type_id: int, fields: list[dict[str, Any]]):
    return rest_api.post('/objects/', json={'public_id': public_id, 'type_id': type_id, 'active': True,
                                            'author_id': 1, 'version': '1.0.0', 'fields': fields})


@pytest.fixture(name='world', scope='module')
def fixture_world(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """
    The PERSON / PERSON_GROUP types (created through the routes, unlicensed), Ada / Bob / Carol, the group
    'Security' listing Ada, an empty group, and an asset whose owner is the group and whose team is Ada and Bob
    """
    _purge(database_manager, database_name)
    person_type_id = _create_special_type(rest_api, 'PERSON')
    group_type_id = _create_special_type(rest_api, 'PERSON_GROUP')
    database_manager.get_collection(CmdbType.COLLECTION, database_name).insert_one(make_type_doc(
        ASSET_TYPE_ID, f'{NAME_PREFIX}asset', fields=[
            {'type': 'text', 'name': 'pr-hostname', 'label': 'Hostname'},
            {'type': 'person', 'name': OWNER_FIELD, 'label': 'Owner', 'person_ref_kind': 'BOTH', 'multiple': False},
            {'type': 'person', 'name': TEAM_FIELD, 'label': 'Team', 'person_ref_kind': 'PERSON', 'multiple': True},
        ],
    ))

    for public_id, name, extra in ((ADA_ID, 'Ada Lovelace', {PersonField.EMAIL.value: 'ada@example.com',
                                                            PersonField.FIRST_NAME.value: 'Ada'}),
                                   (BOB_ID, 'Bob', {}), (CAROL_ID, 'Carol', {})):
        fields = [{'name': PersonField.DISPLAY_NAME.value, 'value': name}]
        fields += [{'name': key, 'value': value} for key, value in extra.items()]
        assert _post_object(rest_api, public_id, person_type_id, fields).status_code == HTTPStatus.OK

    assert _post_object(rest_api, GROUP_ID, group_type_id, [
        {'name': PersonGroupField.NAME.value, 'value': 'Security'},
        {'name': PersonGroupField.EMAIL.value, 'value': 'sec@example.com'},
        # A lone pair for a multiple field: canonicalised to a list by the enforcement
        {'name': MEMBERS, 'value': _sel('PERSON', ADA_ID)},
    ]).status_code == HTTPStatus.OK
    assert _post_object(rest_api, EMPTY_GROUP_ID, group_type_id, [
        {'name': PersonGroupField.NAME.value, 'value': 'Audit'},
    ]).status_code == HTTPStatus.OK
    assert _post_object(rest_api, ASSET_ID, ASSET_TYPE_ID, [
        {'name': 'pr-hostname', 'value': 'srv-01'},
        {'name': OWNER_FIELD, 'value': _sel('PERSON_GROUP', GROUP_ID)},
        {'name': TEAM_FIELD, 'value': [_sel('PERSON', ADA_ID), _sel('PERSON', BOB_ID), _sel('PERSON', ADA_ID)]},
    ]).status_code == HTTPStatus.OK

    yield {'person_type_id': person_type_id, 'group_type_id': group_type_id,
           'objects': database_manager.get_collection(CmdbObject.COLLECTION, database_name)}
    _purge(database_manager, database_name)


def _stored(world: dict[str, Any], public_id: int) -> dict[str, Any]:
    document = world['objects'].find_one({'public_id': public_id})

    return {field['name']: field for field in document['fields']}


def _members(rest_api, group_id: int = GROUP_ID) -> list[int]:
    return [member['id'] for member in rest_api.get(f'{RELATIONS_URL}/{group_id}').get_json()['members']]


@pytest.fixture(name='restore_members')
def fixture_restore_members(world: dict[str, Any]):
    """Puts the group's membership back to [Ada] after a test that edits it"""
    yield
    world['objects'].update_one(
        {'public_id': GROUP_ID, 'fields.name': MEMBERS},
        {'$set': {'fields.$.value': [_sel('PERSON', ADA_ID)], 'fields.$.type': 'person'}},
    )


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 the object write path                                                #
# -------------------------------------------------------------------------------------------------------------------- #
class TestObjectWrite:
    """POST /objects/ runs the person field enforcement"""

    def test_the_values_are_stored_canonically(self, world: dict[str, Any]) -> None:
        """The lone pair became a list, the duplicate went, every person row carries the 'person' type"""
        group = _stored(world, GROUP_ID)
        asset = _stored(world, ASSET_ID)

        assert group[MEMBERS]['value'] == [_sel('PERSON', ADA_ID)]
        assert group[MEMBERS]['type'] == 'person'
        assert asset[TEAM_FIELD]['value'] == [_sel('PERSON', ADA_ID), _sel('PERSON', BOB_ID)]
        assert asset[OWNER_FIELD] == {'name': OWNER_FIELD, 'value': _sel('PERSON_GROUP', GROUP_ID), 'type': 'person'}

    @pytest.mark.parametrize('field, value, fragment', [
        (OWNER_FIELD, _sel('PERSON', UNKNOWN_ID), f'references PERSON {UNKNOWN_ID}, which does not exist'),
        (OWNER_FIELD, _sel('PERSON', GROUP_ID), f'references PERSON {GROUP_ID}, which does not exist'),
        (OWNER_FIELD, _sel('PERSON', ASSET_ID), f'references PERSON {ASSET_ID}, which does not exist'),
        (TEAM_FIELD, [_sel('PERSON_GROUP', GROUP_ID)], "does not allow 'PERSON_GROUP'"),
        (OWNER_FIELD, 'Ada', 'expects a single selection'),
        (OWNER_FIELD, {'ref_type': 'PERSON', 'id': ADA_ID, 'label': 'x'}, "exactly 'ref_type' and 'id'"),
        (TEAM_FIELD, [_sel('PERSON', str(ADA_ID))], 'not a public_id'),
    ], ids=['unknown-id', 'group-as-person', 'ordinary-object', 'wrong-kind', 'text', 'extra-key', 'string-id'])
    def test_a_bad_value_is_refused_and_nothing_stored(self, rest_api, world: dict[str, Any],
                                                       field: str, value: Any, fragment: str) -> None:
        """400 naming the person feature and the problem; no object written"""
        response = _post_object(rest_api, REFUSED_ID, ASSET_TYPE_ID, [{'name': field, 'value': value}])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert 'Person validation failed' in response.get_json()['message']
        assert fragment in response.get_json()['message']
        assert world['objects'].find_one({'public_id': REFUSED_ID}) is None

    def test_a_group_may_only_list_persons(self, rest_api, world: dict[str, Any]) -> None:
        """MEMBERS is restricted to PERSON"""
        response = _post_object(rest_api, REFUSED_ID, world['group_type_id'], [
            {'name': PersonGroupField.NAME.value, 'value': 'Nested'},
            {'name': MEMBERS, 'value': [_sel('PERSON_GROUP', GROUP_ID)]},
        ])

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert world['objects'].find_one({'public_id': REFUSED_ID}) is None


# -------------------------------------------------------------------------------------------------------------------- #
#                                                   the read routes                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestReadRoutes:
    """GET /person_relations/..."""

    def test_types(self, rest_api, world: dict[str, Any]) -> None:
        """The type of each person SpecialType"""
        response = rest_api.get(f'{RELATIONS_URL}/types')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'PERSON': world['person_type_id'], 'PERSON_GROUP': world['group_type_id']}

    @pytest.mark.parametrize('kind, expected', [
        ('PERSON', [ADA_ID, BOB_ID, CAROL_ID]),
        ('PERSON_GROUP', [EMPTY_GROUP_ID, GROUP_ID]),
        ('BOTH', [ADA_ID, EMPTY_GROUP_ID, BOB_ID, CAROL_ID, GROUP_ID]),
        (None, [ADA_ID, EMPTY_GROUP_ID, BOB_ID, CAROL_ID, GROUP_ID]),
    ])
    def test_candidates(self, rest_api, world: dict[str, Any], kind: str | None, expected: list[int]) -> None:
        """What a person field of the kind may select, sorted by label; BOTH is the default"""
        url = f'{RELATIONS_URL}/candidates' + (f'?kind={kind}' if kind else '')
        response = rest_api.get(url)

        assert response.status_code == HTTPStatus.OK
        assert [entry['id'] for entry in response.get_json()] == expected

    def test_a_candidate_entry(self, rest_api, world: dict[str, Any]) -> None:
        """{'ref_type', 'id', 'label', 'type_id'}"""
        entries = rest_api.get(f'{RELATIONS_URL}/candidates?kind=PERSON').get_json()

        assert entries[0] == {'ref_type': 'PERSON', 'id': ADA_ID, 'label': 'Ada Lovelace',
                              'type_id': world['person_type_id']}

    def test_an_unknown_kind_is_refused(self, rest_api, world: dict[str, Any]) -> None:
        """400 for a kind that is no PersonRefKind"""
        assert rest_api.get(f'{RELATIONS_URL}/candidates?kind=USER').status_code == HTTPStatus.BAD_REQUEST

    def test_a_persons_relations(self, rest_api, world: dict[str, Any]) -> None:
        """Ada: member of Security, on the asset's team - the group's MEMBERS field is no assignment"""
        body = rest_api.get(f'{RELATIONS_URL}/{ADA_ID}').get_json()

        assert body['ref_type'] == 'PERSON'
        assert body['label'] == 'Ada Lovelace'
        assert [entry['id'] for entry in body['memberships']] == [GROUP_ID]
        assert body['members'] == []
        assert [(row['object_id'], row['field_name'], row['field_label']) for row in body['assignments']] == [
            (ASSET_ID, TEAM_FIELD, 'Team'),
        ]

    def test_a_groups_relations(self, rest_api, world: dict[str, Any]) -> None:
        """Security: its members, and the asset it owns"""
        body = rest_api.get(f'{RELATIONS_URL}/{GROUP_ID}').get_json()

        assert body['ref_type'] == 'PERSON_GROUP'
        assert [entry['id'] for entry in body['members']] == [ADA_ID]
        assert body['memberships'] == []
        assert [(row['object_id'], row['field_name']) for row in body['assignments']] == [(ASSET_ID, OWNER_FIELD)]

    @pytest.mark.parametrize('object_id', [ASSET_ID, UNKNOWN_ID])
    def test_no_person_is_a_404(self, rest_api, world: dict[str, Any], object_id: int) -> None:
        """An ordinary object or no object at all"""
        assert rest_api.get(f'{RELATIONS_URL}/{object_id}').status_code == HTTPStatus.NOT_FOUND


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  membership writes                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.usefixtures('restore_members')
class TestMembershipWrites:
    """POST / DELETE /person_relations/<group>/members"""

    def test_add_a_member(self, rest_api, world: dict[str, Any]) -> None:
        """Appended, stored canonically, answered with the group's relations"""
        response = rest_api.post(f'{RELATIONS_URL}/{GROUP_ID}/members', json={'person_id': BOB_ID})

        assert response.status_code == HTTPStatus.OK
        assert [entry['id'] for entry in response.get_json()['members']] == [ADA_ID, BOB_ID]
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == [_sel('PERSON', ADA_ID), _sel('PERSON', BOB_ID)]
        assert [entry['id'] for entry in rest_api.get(f'{RELATIONS_URL}/{BOB_ID}').get_json()['memberships']] \
            == [GROUP_ID]

    def test_adding_a_member_twice_changes_nothing(self, rest_api, world: dict[str, Any]) -> None:
        """Idempotent"""
        response = rest_api.post(f'{RELATIONS_URL}/{GROUP_ID}/members', json={'person_id': ADA_ID})

        assert response.status_code == HTTPStatus.OK
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == [_sel('PERSON', ADA_ID)]

    def test_add_to_an_empty_group(self, rest_api, world: dict[str, Any]) -> None:
        """A group created without the MEMBERS value"""
        response = rest_api.post(f'{RELATIONS_URL}/{EMPTY_GROUP_ID}/members', json={'person_id': CAROL_ID})

        try:
            assert response.status_code == HTTPStatus.OK
            assert _members(rest_api, EMPTY_GROUP_ID) == [CAROL_ID]
        finally:
            rest_api.delete(f'{RELATIONS_URL}/{EMPTY_GROUP_ID}/members/{CAROL_ID}')

    @pytest.mark.parametrize('body', [{}, {'person_id': 'x'}, {'person_id': True}, {'person_id': None}, ['x']])
    def test_a_bad_body_is_a_400(self, rest_api, world: dict[str, Any], body: Any) -> None:
        """'person_id' must be a public_id"""
        response = rest_api.post(f'{RELATIONS_URL}/{GROUP_ID}/members', json=body)

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == [_sel('PERSON', ADA_ID)]

    @pytest.mark.parametrize('person_id', [UNKNOWN_ID, EMPTY_GROUP_ID, ASSET_ID])
    def test_a_member_that_is_no_person_is_a_400(self, rest_api, world: dict[str, Any], person_id: int) -> None:
        """Judged by the object write enforcement: unknown, a group, an ordinary object"""
        response = rest_api.post(f'{RELATIONS_URL}/{GROUP_ID}/members', json={'person_id': person_id})

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == [_sel('PERSON', ADA_ID)]

    @pytest.mark.parametrize('group_id', [ADA_ID, ASSET_ID, UNKNOWN_ID])
    def test_a_target_that_is_no_group_is_a_404(self, rest_api, world: dict[str, Any], group_id: int) -> None:
        """A person, an ordinary object, nothing"""
        assert rest_api.post(f'{RELATIONS_URL}/{group_id}/members', json={'person_id': BOB_ID}).status_code \
            == HTTPStatus.NOT_FOUND
        assert rest_api.delete(f'{RELATIONS_URL}/{group_id}/members/{BOB_ID}').status_code == HTTPStatus.NOT_FOUND

    def test_remove_a_member(self, rest_api, world: dict[str, Any]) -> None:
        """Removed from the MEMBERS field; Ada's membership is gone"""
        response = rest_api.delete(f'{RELATIONS_URL}/{GROUP_ID}/members/{ADA_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['members'] == []
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == []
        assert rest_api.get(f'{RELATIONS_URL}/{ADA_ID}').get_json()['memberships'] == []

    def test_removing_a_non_member_changes_nothing(self, rest_api, world: dict[str, Any]) -> None:
        """Idempotent"""
        response = rest_api.delete(f'{RELATIONS_URL}/{GROUP_ID}/members/{CAROL_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == [_sel('PERSON', ADA_ID)]


# -------------------------------------------------------------------------------------------------------------------- #
#                                               the legacy ISMS read routes                                            #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.fixture(name='isms_licensed')
def fixture_isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """GET /persons and /person_groups stay ISMS-license gated"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.mark.usefixtures('isms_licensed')
class TestLegacyRoutes:
    """The shape of the former management.person / management.personGroup documents"""

    def test_get_persons(self, rest_api, world: dict[str, Any]) -> None:
        """Every person, sorted by display name, with the groups listing it"""
        response = rest_api.get('/persons/')

        assert response.status_code == HTTPStatus.OK
        results = [row for row in response.get_json()['results'] if row['public_id'] in ALL_OBJECT_IDS]
        assert [row['public_id'] for row in results] == [ADA_ID, BOB_ID, CAROL_ID]
        assert results[0] == {
            'public_id': ADA_ID, 'display_name': 'Ada Lovelace', 'first_name': 'Ada', 'last_name': '',
            'phone_number': '', 'email': 'ada@example.com', 'groups': [GROUP_ID],
        }
        assert results[1]['groups'] == []

    def test_get_persons_pages(self, rest_api, world: dict[str, Any]) -> None:
        """'limit' and 'page' are honoured; the total counts every person"""
        body = rest_api.get('/persons/?limit=1&page=2').get_json()

        assert len(body['results']) == 1
        assert body['total'] >= 3

    def test_get_one_person(self, rest_api, world: dict[str, Any]) -> None:
        """The single route answers the same shape"""
        response = rest_api.get(f'/persons/{BOB_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()['result']['display_name'] == 'Bob'

    @pytest.mark.parametrize('url', [f'/persons/{GROUP_ID}', f'/persons/{ASSET_ID}', f'/person_groups/{ADA_ID}'])
    def test_an_object_of_another_kind_is_a_404(self, rest_api, world: dict[str, Any], url: str) -> None:
        """A group is no person, a person no group, an asset neither"""
        assert rest_api.get(url).status_code == HTTPStatus.NOT_FOUND

    def test_get_person_groups(self, rest_api, world: dict[str, Any]) -> None:
        """Every group, sorted by name, with its members"""
        response = rest_api.get('/person_groups/')

        assert response.status_code == HTTPStatus.OK
        results = [row for row in response.get_json()['results'] if row['public_id'] in ALL_OBJECT_IDS]
        assert results == [
            {'public_id': EMPTY_GROUP_ID, 'name': 'Audit', 'email': '', 'group_members': []},
            {'public_id': GROUP_ID, 'name': 'Security', 'email': 'sec@example.com', 'group_members': [ADA_ID]},
        ]
        assert rest_api.get(f'/person_groups/{GROUP_ID}').get_json()['result']['group_members'] == [ADA_ID]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      CI Explorer                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCiExplorer:
    """GET /ci_explorer/items grafts the person neighbours in"""

    def test_the_assets_persons_are_children(self, rest_api, world: dict[str, Any]) -> None:
        """The owner group and the team, each edge named after its field"""
        body = rest_api.get(f'/ci_explorer/items?target_id={ASSET_ID}&with_person_relations=true').get_json()

        edges = {(edge['to'], edge['metadata']['relation_label']) for edge in body['child_edges']
                 if edge['metadata'].get('source') == 'person'}

        assert edges == {(GROUP_ID, 'Owner'), (ADA_ID, 'Team'), (BOB_ID, 'Team')}

    def test_a_person_has_its_selectors_as_parents(self, rest_api, world: dict[str, Any]) -> None:
        """Ada is selected by the asset's team and listed by the group"""
        body = rest_api.get(f'/ci_explorer/items?target_id={ADA_ID}&with_person_relations=true').get_json()

        edges = {(edge['from'], edge['metadata']['relation_label']) for edge in body['parent_edges']
                 if edge['metadata'].get('source') == 'person'}

        assert edges == {(ASSET_ID, 'Team'), (GROUP_ID, 'Members')}

    def test_the_toggle_off_grafts_nothing(self, rest_api, world: dict[str, Any]) -> None:
        """with_person_relations=false"""
        body = rest_api.get(f'/ci_explorer/items?target_id={ASSET_ID}&with_person_relations=false').get_json()

        assert not [edge for edge in body['child_edges'] if edge['metadata'].get('source') == 'person']


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 deleting a person                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestDelete:
    """Runs last in the module: it deletes Ada"""

    def test_deleting_a_person_scrubs_every_person_field(self, rest_api, world: dict[str, Any]) -> None:
        """Gone from the group's members and from the asset's team"""
        response = rest_api.delete(f'/objects/{ADA_ID}')

        assert response.status_code == HTTPStatus.OK
        assert _stored(world, GROUP_ID)[MEMBERS]['value'] == []
        assert _stored(world, ASSET_ID)[TEAM_FIELD]['value'] == [_sel('PERSON', BOB_ID)]
        assert _stored(world, ASSET_ID)[OWNER_FIELD]['value'] == _sel('PERSON_GROUP', GROUP_ID)

    def test_deleting_a_group_clears_a_single_selection(self, rest_api, world: dict[str, Any]) -> None:
        """The asset's owner was the group"""
        assert rest_api.delete(f'/objects/{GROUP_ID}').status_code == HTTPStatus.OK
        assert _stored(world, ASSET_ID)[OWNER_FIELD]['value'] is None
