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
Functional tests for the assessed object of a RiskAssessment write, over HTTP

Pinned on create, update and duplicate:

  - a CmdbObject that does not exist and one of a type the writer may not READ get the SAME 400, so the answer says
    nothing about objects the writer cannot see; an administrator may assess the second
  - a CmdbObjectGroup that does not exist is a 400; a stored group passes (groups carry no ACL)
  - an update judges the assessed object only when it changes: an assessment whose stored object is gone is still
    saved unchanged, moving it onto a missing or hidden object is refused and nothing changes
  - a duplicate judges every target of an object / object_group duplicate - and the payload's own object in risk
    mode - before the first copy, so a refused duplicate writes none
  - a failed read of the objects or of the writer's readable types is its own 400, not a 500
"""
from datetime import datetime, timezone
from functools import partial
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.errors.manager import BaseManagerGetError
from cmdb.manager.isms_manager.risk_assessment_manager import RiskAssessmentManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.object_group_model import ObjectReferenceType
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.models.user_model import CmdbUser
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.interface.rest_api.routes.isms_routes import isms_routes_helper
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ASSESSED_OBJECT_LOOKUP_FAILED_MSG,
    UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG,
    UNKNOWN_ASSESSED_OBJECTS_MSG,
)
from tests.functional.isms.test_functional_risk_assessment_route import (
    RISK_ID,
    _ra_body,
    purge_referenced_persons,
    purge_referenced_risks,
    seed_referenced_persons,
    seed_referenced_risks,
)
from tests.utils.isms_reference_seed import ASSESSED_OBJECT_GROUP_ID
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/risk_assessments'
MESSAGE_KEY: str = 'message'
OBJECT: str = ObjectReferenceType.OBJECT.value
OBJECT_GROUP: str = ObjectReferenceType.OBJECT_GROUP.value

OPEN_TYPE_ID: int = 98951
HIDDEN_TYPE_ID: int = 98952
OPEN_OBJECT_ID: int = 98953
SECOND_OPEN_OBJECT_ID: int = 98954
HIDDEN_OBJECT_ID: int = 98955
MISSING_OBJECT_ID: int = 98959
MISSING_GROUP_ID: int = 98958
NEW_RA_ID: int = 98961
STORED_RA_ID: int = 98962
STALE_RA_ID: int = 98963
SECOND_RISK_ID: int = 98964
SENT_RISK_IDS: list[int] = [RISK_ID, SECOND_RISK_ID]

WRITER_GROUP_ID: int = 98971
WRITER_ID: int = 98972
WRITER_NAME: str = 'isms-assessed-object-writer'
WRITER_RIGHTS: list[str] = ['base.isms.riskAssessment.add', 'base.isms.riskAssessment.edit']

ADMIN_ALL: dict[str, list[str]] = {str(ADMIN_GROUP_ID): ['CREATE', 'READ', 'UPDATE', 'DELETE']}
HIDDEN_ACL: dict[str, Any] = {'activated': True, 'groups': {'includes': ADMIN_ALL}}
OPEN_ACL: dict[str, Any] = {'activated': False, 'groups': {'includes': None}}


def _type(public_id: int, acl: dict[str, Any]) -> dict[str, Any]:
    """A CmdbType with the given ACL"""
    return {'public_id': public_id, 'name': f'assessed-{public_id}', 'label': f'Assessed {public_id}', 'author_id': 1,
            'active': True, 'creation_time': datetime.now(timezone.utc), 'version': '1.0.0', 'acl': acl,
            'fields': [], 'render_meta': {'icon': 'fa-cube', 'summary': {'fields': []}, 'sections': []}}


def _object(public_id: int, type_id: int) -> dict[str, Any]:
    """A CmdbObject of the given type"""
    return {'public_id': public_id, 'type_id': type_id, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': []}


SEEDS: dict[str, list[dict[str, Any]]] = {
    CmdbType.COLLECTION: [_type(OPEN_TYPE_ID, OPEN_ACL), _type(HIDDEN_TYPE_ID, HIDDEN_ACL)],
    CmdbObject.COLLECTION: [_object(OPEN_OBJECT_ID, OPEN_TYPE_ID), _object(SECOND_OPEN_OBJECT_ID, OPEN_TYPE_ID),
                            _object(HIDDEN_OBJECT_ID, HIDDEN_TYPE_ID)],
    CmdbUserGroup.COLLECTION: [
        {'public_id': WRITER_GROUP_ID, 'name': WRITER_NAME, 'label': WRITER_NAME, 'rights': WRITER_RIGHTS},
    ],
    CmdbUser.COLLECTION: [{'public_id': WRITER_ID, 'user_name': WRITER_NAME, 'active': True,
                           'group_id': WRITER_GROUP_ID, 'registration_time': datetime.now(timezone.utc)}],
}


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='assessments', autouse=True)
def fixture_assessments(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """
    The types, objects and writer; persons and Risks; an assessment of an open object and one whose object is gone.
    Everything the tests write is removed again
    """
    collection = partial(database_manager.get_collection, db_name=database_name)
    assessments = collection(IsmsRiskAssessment.COLLECTION)

    def _purge() -> None:
        for name, docs in SEEDS.items():
            collection(name).delete_many({'public_id': {'$in': [doc['public_id'] for doc in docs]}})
        assessments.delete_many({'risk_id': {'$in': SENT_RISK_IDS}})
        purge_referenced_persons(database_manager, database_name)
        purge_referenced_risks(database_manager, database_name, tuple(SENT_RISK_IDS))

    _purge()
    for name, docs in SEEDS.items():
        collection(name).insert_many([dict(doc) for doc in docs])
    seed_referenced_persons(database_manager, database_name)
    seed_referenced_risks(database_manager, database_name, tuple(SENT_RISK_IDS))
    assessments.insert_many([
        _ra_body(STORED_RA_ID, object_id_ref_type=OBJECT, object_id=OPEN_OBJECT_ID),
        _ra_body(STALE_RA_ID, object_id_ref_type=OBJECT, object_id=MISSING_OBJECT_ID),
    ])
    yield assessments
    _purge()


@pytest.fixture(name='writer')
def fixture_writer() -> CmdbUser:
    """The seeded writer: the RiskAssessment write rights, no READ on the hidden type"""
    return CmdbUser(public_id=WRITER_ID, user_name=WRITER_NAME, active=True, group_id=WRITER_GROUP_ID)


def _body(ref_type: str, object_id: int, public_id: int = NEW_RA_ID) -> dict[str, Any]:
    """A complete body assessing the given object or group"""
    return _ra_body(public_id, object_id_ref_type=ref_type, object_id=object_id)


def _written(assessments: Any) -> int:
    """How many assessments the tests wrote: every one but the two stored ones"""
    return assessments.count_documents({'public_id': {'$nin': [STORED_RA_ID, STALE_RA_ID]},
                                        'risk_id': {'$in': SENT_RISK_IDS}})


def _refused(response: Any, message: str) -> None:
    """A 400 with exactly this message"""
    assert (response.status_code, response.get_json()[MESSAGE_KEY]) == (HTTPStatus.BAD_REQUEST, message)


class TestCreate:
    """POST /isms/risk_assessments/"""

    @pytest.mark.parametrize('object_id', [MISSING_OBJECT_ID, HIDDEN_OBJECT_ID], ids=['missing', 'hidden'])
    def test_a_missing_and_a_hidden_object_get_the_same_400(self, rest_api, assessments, writer: CmdbUser,
                                                            object_id: int) -> None:
        """Nothing tells the two apart; nothing is written"""
        _refused(rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT, object_id), user=writer),
                 UNKNOWN_ASSESSED_OBJECTS_MSG.format(unknown=[object_id]))
        assert _written(assessments) == 0

    def test_a_readable_object_passes(self, rest_api, assessments, writer: CmdbUser) -> None:
        """The control"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT, OPEN_OBJECT_ID),
                             user=writer).status_code == HTTPStatus.CREATED
        assert _written(assessments) == 1

    def test_an_administrator_may_assess_the_hidden_object(self, rest_api, assessments) -> None:
        """The ACL grants them READ"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT, HIDDEN_OBJECT_ID)).status_code == HTTPStatus.CREATED

    def test_a_missing_group_is_a_400(self, rest_api, assessments, writer: CmdbUser) -> None:
        """Judged by existence"""
        _refused(rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT_GROUP, MISSING_GROUP_ID), user=writer),
                 UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG.format(unknown=[MISSING_GROUP_ID]))
        assert _written(assessments) == 0

    def test_a_stored_group_passes(self, rest_api, assessments, writer: CmdbUser) -> None:
        """Groups carry no ACL"""
        assert rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT_GROUP, ASSESSED_OBJECT_GROUP_ID),
                             user=writer).status_code == HTTPStatus.CREATED

    def test_a_failed_object_read_is_its_own_400(self, rest_api, assessments, monkeypatch) -> None:
        """Not a 500"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise BaseManagerGetError('objects unreadable')

        monkeypatch.setattr(RiskAssessmentManager, 'get_missing_assessed_ids', _failing)

        _refused(rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT, OPEN_OBJECT_ID)), ASSESSED_OBJECT_LOOKUP_FAILED_MSG)
        assert _written(assessments) == 0

    def test_a_failed_type_read_is_its_own_400(self, rest_api, assessments, monkeypatch) -> None:
        """The readable types are part of the check"""
        def _failing(*_args: Any, **_kwargs: Any) -> Any:
            raise BaseManagerGetError('types unreadable')

        monkeypatch.setattr(isms_routes_helper, 'resolve_denied_type_ids', _failing)

        _refused(rest_api.post(f'{ROUTE_URL}/', json=_body(OBJECT, OPEN_OBJECT_ID)), ASSESSED_OBJECT_LOOKUP_FAILED_MSG)


class TestUpdate:
    """PUT /isms/risk_assessments/<id>"""

    def test_a_stored_object_that_is_gone_does_not_block_a_save(self, rest_api, assessments) -> None:
        """It is not judged again"""
        response = rest_api.put(f'{ROUTE_URL}/{STALE_RA_ID}', json=_body(OBJECT, MISSING_OBJECT_ID, STALE_RA_ID))

        assert response.status_code == HTTPStatus.ACCEPTED

    @pytest.mark.parametrize('object_id', [MISSING_OBJECT_ID, HIDDEN_OBJECT_ID], ids=['missing', 'hidden'])
    def test_moving_onto_a_missing_or_hidden_object_is_a_400(self, rest_api, assessments, writer: CmdbUser,
                                                             object_id: int) -> None:
        """The stored assessment keeps its object"""
        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_body(OBJECT, object_id, STORED_RA_ID),
                                user=writer)

        _refused(response, UNKNOWN_ASSESSED_OBJECTS_MSG.format(unknown=[object_id]))
        assert assessments.find_one({'public_id': STORED_RA_ID})['object_id'] == OPEN_OBJECT_ID

    def test_changing_only_the_reference_type_is_judged(self, rest_api, assessments) -> None:
        """The same id as a group names another document"""
        _refused(rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_body(OBJECT_GROUP, OPEN_OBJECT_ID, STORED_RA_ID)),
                 UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG.format(unknown=[OPEN_OBJECT_ID]))

    def test_moving_onto_another_readable_object_passes(self, rest_api, assessments, writer: CmdbUser) -> None:
        """The control"""
        response = rest_api.put(f'{ROUTE_URL}/{STORED_RA_ID}', json=_body(OBJECT, SECOND_OPEN_OBJECT_ID, STORED_RA_ID),
                                user=writer)

        assert response.status_code == HTTPStatus.ACCEPTED
        assert assessments.find_one({'public_id': STORED_RA_ID})['object_id'] == SECOND_OPEN_OBJECT_ID


class TestDuplicate:
    """POST /isms/risk_assessments/duplicate/<mode>/<ids>"""

    def test_an_object_duplicate_refuses_every_missing_or_hidden_target_and_writes_none(
            self, rest_api, assessments, writer: CmdbUser) -> None:
        """Judged in one read before the first copy"""
        targets: str = f'{OPEN_OBJECT_ID},{HIDDEN_OBJECT_ID},{MISSING_OBJECT_ID}'

        response = rest_api.post(f'{ROUTE_URL}/duplicate/object/{targets}?copy_cma=false',
                                 json=_body(OBJECT, OPEN_OBJECT_ID, STORED_RA_ID), user=writer)

        _refused(response, UNKNOWN_ASSESSED_OBJECTS_MSG.format(unknown=[HIDDEN_OBJECT_ID, MISSING_OBJECT_ID]))
        assert _written(assessments) == 0

    def test_an_object_group_duplicate_refuses_a_missing_group(self, rest_api, assessments) -> None:
        """Nothing written"""
        response = rest_api.post(f'{ROUTE_URL}/duplicate/object_group/{MISSING_GROUP_ID}?copy_cma=false',
                                 json=_body(OBJECT_GROUP, ASSESSED_OBJECT_GROUP_ID, STORED_RA_ID))

        _refused(response, UNKNOWN_ASSESSED_OBJECT_GROUPS_MSG.format(unknown=[MISSING_GROUP_ID]))
        assert _written(assessments) == 0

    def test_a_risk_duplicate_judges_the_payloads_object(self, rest_api, assessments) -> None:
        """Every copy carries it"""
        response = rest_api.post(f'{ROUTE_URL}/duplicate/risk/{SECOND_RISK_ID}?copy_cma=false',
                                 json=_body(OBJECT, MISSING_OBJECT_ID, STORED_RA_ID))

        _refused(response, UNKNOWN_ASSESSED_OBJECTS_MSG.format(unknown=[MISSING_OBJECT_ID]))
        assert _written(assessments) == 0

    def test_readable_targets_are_copied(self, rest_api, assessments, writer: CmdbUser) -> None:
        """The control - one copy per target"""
        response = rest_api.post(f'{ROUTE_URL}/duplicate/object/{OPEN_OBJECT_ID},{SECOND_OPEN_OBJECT_ID}'
                                 '?copy_cma=false', json=_body(OBJECT, OPEN_OBJECT_ID, STORED_RA_ID), user=writer)

        assert response.status_code == HTTPStatus.OK
        assert _written(assessments) == 2
