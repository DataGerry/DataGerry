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
Integration tests: ObjectsManager.delete_all_object_references for persons and groups, against a real MongoDB

When a person or group object is deleted, the object delete path scrubs it from

  - every person field selecting it: a single selection becomes None, a multiple one loses the entry (top-level
    fields and multi-data-section rows alike) - the split on the BSON type of the value is what a stubbed manager
    cannot prove, since '$pull' on a non-array would fail the whole write
  - every ISMS reference (risk assessment and control measure assignment), matched by the bare id

and leaves everything else - other selections, other ids, non-person fields holding an 'id' - alone.
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.isms_model import IsmsControlMeasureAssignment, IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
# -------------------------------------------------------------------------------------------------------------------- #

ADA: int = 96101         # deleted
BOB: int = 96102         # kept
SECURITY: int = 96103    # deleted group
ASSET: int = 96111
MDS_ASSET: int = 96112
BYSTANDER: int = 96113
OBJECT_IDS: list[int] = [ASSET, MDS_ASSET, BYSTANDER]

RISK_ASSESSMENT_ID: int = 96121
OTHER_RISK_ASSESSMENT_ID: int = 96122
ASSIGNMENT_ID: int = 96123


def _sel(ref_type: str, object_id: int) -> dict[str, Any]:
    return {'ref_type': ref_type, 'id': object_id}


def _object(public_id: int, fields: list[dict[str, Any]], mds: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {'public_id': public_id, 'type_id': 96199, 'active': True, 'author_id': 1, 'version': '1.0.0',
            'creation_time': datetime.now(timezone.utc), 'fields': fields, 'multi_data_sections': mds or []}


@pytest.fixture(name='seeded')
def fixture_seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Objects selecting the persons, ISMS documents referencing them - purged after"""
    database = database_manager.get_collection(CmdbObject.COLLECTION, database_name).database
    objects = database[CmdbObject.COLLECTION]
    assessments = database[IsmsRiskAssessment.COLLECTION]
    assignments = database[IsmsControlMeasureAssignment.COLLECTION]

    def _purge() -> None:
        objects.delete_many({'public_id': {'$in': OBJECT_IDS}})
        assessments.delete_many({'public_id': {'$in': [RISK_ASSESSMENT_ID, OTHER_RISK_ASSESSMENT_ID]}})
        assignments.delete_many({'public_id': ASSIGNMENT_ID})

    _purge()
    objects.insert_many([
        _object(ASSET, [
            {'name': 'owner', 'type': 'person', 'value': _sel('PERSON', ADA)},
            {'name': 'deputy', 'type': 'person', 'value': _sel('PERSON', BOB)},
            {'name': 'team', 'type': 'person', 'value': [_sel('PERSON', BOB), _sel('PERSON', ADA),
                                                         _sel('PERSON_GROUP', SECURITY)]},
            {'name': 'empty', 'type': 'person', 'value': None},
            {'name': 'nobody', 'type': 'person', 'value': []},
            {'name': 'link', 'type': 'ref', 'value': ADA},
        ]),
        _object(MDS_ASSET, [{'name': 'hostname', 'type': 'text', 'value': 'srv'}], mds=[
            {'section_id': 'contacts', 'highest_id': 2, 'values': [
                {'multi_data_id': 0, 'data': [{'name': 'contact', 'type': 'person', 'value': _sel('PERSON', ADA)}]},
                {'multi_data_id': 1, 'data': [{'name': 'contact', 'type': 'person',
                                               'value': [_sel('PERSON', ADA), _sel('PERSON', BOB)]}]},
                {'multi_data_id': 2, 'data': [{'name': 'contact', 'type': 'person', 'value': _sel('PERSON', BOB)}]},
            ]},
        ]),
        # A non-person field whose value carries an 'id' must not be touched
        _object(BYSTANDER, [{'name': 'json', 'type': 'text', 'value': {'id': ADA}}]),
    ])
    assessments.insert_many([
        {'public_id': RISK_ASSESSMENT_ID,
         'risk_owner_id': ADA, 'risk_owner_id_ref_type': 'PERSON',
         'responsible_persons_id': SECURITY, 'responsible_persons_id_ref_type': 'PERSON_GROUP',
         'auditor_id': BOB, 'auditor_id_ref_type': 'PERSON',
         'risk_assessor_id': ADA,
         'interviewed_persons': [BOB, ADA]},
        {'public_id': OTHER_RISK_ASSESSMENT_ID,
         'risk_owner_id': BOB, 'risk_owner_id_ref_type': 'PERSON',
         'risk_assessor_id': BOB, 'interviewed_persons': [BOB]},
    ])
    assignments.insert_one({'public_id': ASSIGNMENT_ID, 'responsible_for_implementation_id': SECURITY,
                            'responsible_for_implementation_id_ref_type': 'PERSON_GROUP'})
    yield database
    _purge()


def _scrub(database_manager: MongoDatabaseManager, database_name: str, ids: Any) -> None:
    ObjectsManager(database_manager, database_name).delete_all_object_references(ids)


def _values(database: Any, public_id: int) -> dict[str, Any]:
    document = database[CmdbObject.COLLECTION].find_one({'public_id': public_id})

    return {field['name']: field['value'] for field in document['fields']}


def _mds_values(database: Any) -> list[Any]:
    document = database[CmdbObject.COLLECTION].find_one({'public_id': MDS_ASSET})

    return [row['data'][0]['value'] for row in document['multi_data_sections'][0]['values']]


class TestPersonFieldScrub:
    """The person fields of the remaining objects"""

    def test_a_single_selection_becomes_none(self, database_manager: MongoDatabaseManager, database_name: str,
                                             seeded: Any) -> None:
        """The owner pointed at Ada; the deputy (Bob) stays"""
        _scrub(database_manager, database_name, [ADA])

        values = _values(seeded, ASSET)

        assert values['owner'] is None
        assert values['deputy'] == _sel('PERSON', BOB)

    def test_a_list_loses_only_the_deleted_entry(self, database_manager: MongoDatabaseManager, database_name: str,
                                                 seeded: Any) -> None:
        """Bob and the group stay, in order"""
        _scrub(database_manager, database_name, [ADA])

        assert _values(seeded, ASSET)['team'] == [_sel('PERSON', BOB), _sel('PERSON_GROUP', SECURITY)]

    def test_empty_values_are_left_as_they_are(self, database_manager: MongoDatabaseManager, database_name: str,
                                               seeded: Any) -> None:
        """None and [] are no selection of anyone"""
        _scrub(database_manager, database_name, [ADA])

        values = _values(seeded, ASSET)

        assert values['empty'] is None
        assert values['nobody'] == []

    def test_the_reference_scrub_still_runs(self, database_manager: MongoDatabaseManager, database_name: str,
                                            seeded: Any) -> None:
        """A plain 'ref' field naming the deleted object is emptied as before"""
        _scrub(database_manager, database_name, [ADA])

        assert _values(seeded, ASSET)['link'] == ''

    def test_the_mds_rows_are_scrubbed(self, database_manager: MongoDatabaseManager, database_name: str,
                                       seeded: Any) -> None:
        """Single and multiple selections inside multi-data-section rows"""
        _scrub(database_manager, database_name, [ADA])

        assert _mds_values(seeded) == [None, [_sel('PERSON', BOB)], _sel('PERSON', BOB)]

    def test_a_group_is_scrubbed_like_a_person(self, database_manager: MongoDatabaseManager, database_name: str,
                                               seeded: Any) -> None:
        """A scalar id (the single delete) of a group"""
        _scrub(database_manager, database_name, SECURITY)

        assert _values(seeded, ASSET)['team'] == [_sel('PERSON', BOB), _sel('PERSON', ADA)]
        assert _values(seeded, ASSET)['owner'] == _sel('PERSON', ADA)

    def test_several_ids_at_once(self, database_manager: MongoDatabaseManager, database_name: str,
                                 seeded: Any) -> None:
        """The bulk delete passes a list"""
        _scrub(database_manager, database_name, [ADA, SECURITY])

        assert _values(seeded, ASSET)['team'] == [_sel('PERSON', BOB)]

    def test_a_non_person_field_is_not_touched(self, database_manager: MongoDatabaseManager, database_name: str,
                                               seeded: Any) -> None:
        """Only rows typed 'person' are scrubbed"""
        _scrub(database_manager, database_name, [ADA])

        assert _values(seeded, BYSTANDER)['json'] == {'id': ADA}


class TestIsmsClear:
    """The ISMS documents referencing a deleted person or group"""

    def test_the_risk_assessment_references_are_cleared(self, database_manager: MongoDatabaseManager,
                                                        database_name: str, seeded: Any) -> None:
        """Scalars nulled, the interviewed list pulled; the '_ref_type' siblings stay; Bob's references stay"""
        _scrub(database_manager, database_name, [ADA, SECURITY])

        assessment = seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RISK_ASSESSMENT_ID})

        assert assessment['risk_owner_id'] is None
        assert assessment['risk_owner_id_ref_type'] == 'PERSON'
        assert assessment['responsible_persons_id'] is None
        assert assessment['auditor_id'] == BOB
        assert assessment['risk_assessor_id'] is None
        assert assessment['interviewed_persons'] == [BOB]

    def test_the_assignment_reference_is_cleared(self, database_manager: MongoDatabaseManager, database_name: str,
                                                 seeded: Any) -> None:
        """The responsible group of a control measure assignment"""
        _scrub(database_manager, database_name, SECURITY)

        assignment = seeded[IsmsControlMeasureAssignment.COLLECTION].find_one({'public_id': ASSIGNMENT_ID})

        assert assignment['responsible_for_implementation_id'] is None

    def test_an_unrelated_assessment_is_untouched(self, database_manager: MongoDatabaseManager, database_name: str,
                                                  seeded: Any) -> None:
        """Only the documents naming a deleted id change"""
        before = seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': OTHER_RISK_ASSESSMENT_ID})

        _scrub(database_manager, database_name, [ADA, SECURITY])

        assert seeded[IsmsRiskAssessment.COLLECTION].find_one({'public_id': OTHER_RISK_ASSESSMENT_ID}) == before
