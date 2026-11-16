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
Integration tests of the person / group reads and the ISMS clean-up against a real MongoDB

Persons and groups are objects of the test person Types; one more person of a Type the reader may not READ. Pinned:
the report's ``$lookup`` joins a scalar and a list field, projects the name under the label field's key and leaves
the hidden person out; the names skip the hidden person; the owner count and the clean-up touch exactly the references
whose id AND ref_type match
"""
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager import ObjectsManager
from cmdb.models.isms_model import IsmsRiskAssessment
from cmdb.models.object_model import CmdbObject
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.person_group_model.person_reference_type_enum import PersonReferenceType
from cmdb.framework.person_types.person_object_references import marked_object_lookup, marked_object_names
from cmdb.framework.person_types.person_isms_cleanup import (
    clear_isms_person_references,
    count_owned_risk_assessments,
)
from tests.utils.person_objects import person_object_doc, purge_person_objects, seed_person_objects
# -------------------------------------------------------------------------------------------------------------------- #

ADA, BOB, HIDDEN = 96801, 96802, 96803
TEAM: int = 96804
HIDDEN_TYPE: int = 96809
RA_ID: int = 96810


@pytest.fixture(name='db')
def fixture_db(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The persons, the group, the hidden person and an assessment naming them; purged before and after"""
    db = database_manager.connector.client[database_name]

    def _purge() -> None:
        db[IsmsRiskAssessment.COLLECTION].delete_many({'public_id': RA_ID})
        purge_person_objects(database_manager, database_name, [ADA, BOB, HIDDEN, TEAM])

    _purge()
    seed_person_objects(database_manager, database_name, persons={ADA: 'Ada', BOB: 'Bob'}, groups={TEAM: 'Team'})
    hidden = person_object_doc(HIDDEN, SpecialType.PERSON, 'Hidden')
    hidden['type_id'] = HIDDEN_TYPE
    db[CmdbObject.COLLECTION].insert_one(hidden)
    db[IsmsRiskAssessment.COLLECTION].insert_one({
        'public_id': RA_ID, 'risk_owner_id': ADA, 'risk_owner_id_ref_type': 'PERSON',
        'responsible_persons_id': TEAM, 'responsible_persons_id_ref_type': 'PERSON_GROUP',
        'auditor_id': BOB, 'auditor_id_ref_type': 'PERSON', 'risk_assessor_id': HIDDEN,
        'interviewed_persons': [BOB, HIDDEN, ADA],
    })
    yield db
    _purge()


def _joined(db: Any, local_field: str, marker: SpecialType) -> list[dict[str, Any]]:
    """The assessment's joined objects for one field, the hidden Type denied"""
    return list(db[IsmsRiskAssessment.COLLECTION].aggregate([
        {'$match': {'public_id': RA_ID}},
        marked_object_lookup(local_field, 'joined', marker, [HIDDEN_TYPE]),
    ]))[0]['joined']


def test_the_lookup_joins_a_scalar_and_projects_the_name(db) -> None:
    """The group under its key 'name'"""
    assert _joined(db, 'responsible_persons_id', SpecialType.PERSON_GROUP) == [{'public_id': TEAM, 'name': 'Team'}]


def test_the_lookup_joins_a_list_and_leaves_the_hidden_out(db) -> None:
    """Every readable entry, each under 'display_name'"""
    joined = _joined(db, 'interviewed_persons', SpecialType.PERSON)

    assert sorted((row['public_id'], row['display_name']) for row in joined) == [(ADA, 'Ada'), (BOB, 'Bob')]


def test_the_lookup_asks_the_marker(db) -> None:
    """The group is no person"""
    assert not _joined(db, 'responsible_persons_id', SpecialType.PERSON)


def test_the_names_skip_the_hidden_person(database_manager: MongoDatabaseManager, db) -> None:
    """One read, the denied Type left out"""
    del db
    names = marked_object_names(ObjectsManager(database_manager), SpecialType.PERSON, {ADA, HIDDEN, TEAM},
                                [HIDDEN_TYPE])

    assert names == {ADA: 'Ada'}


def test_the_owner_count_and_the_cleanup_match_id_and_ref_type(database_manager: MongoDatabaseManager, db) -> None:
    """ADA owns it; BOB and HIDDEN leave every person key; TEAM as a person touches nothing"""
    manager = ObjectsManager(database_manager)

    assert count_owned_risk_assessments(manager, {PersonReferenceType.PERSON: [ADA]}) == 1
    assert count_owned_risk_assessments(manager, {PersonReferenceType.PERSON_GROUP: [ADA]}) == 0

    clear_isms_person_references(manager, {PersonReferenceType.PERSON: [BOB, HIDDEN, TEAM]})
    assessment = db[IsmsRiskAssessment.COLLECTION].find_one({'public_id': RA_ID})

    assert (assessment['auditor_id'], assessment['risk_assessor_id'], assessment['interviewed_persons'],
            assessment['responsible_persons_id'], assessment['risk_owner_id']) == (None, None, [ADA], TEAM, ADA)
