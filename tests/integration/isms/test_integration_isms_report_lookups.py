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
Integration tests for the shared ISMS report lookup builders against a real MongoDB

``object_reference_lookup_stages`` joins only the one key each report column reads - not the CmdbObject's
``fields`` - and ``risk_reference_lookup_stages`` keeps an assessment whose risk no longer exists
"""
from datetime import datetime, timezone
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.isms_model import IsmsRisk, IsmsRiskAssessment
from cmdb.models.object_group_model import CmdbObjectGroup
from cmdb.models.object_model import CmdbObject
from cmdb.models.type_model import CmdbType
from cmdb.utils import Builder
from cmdb.interface.rest_api.routes.isms_routes.isms_report_constants import ReportAlias
from cmdb.interface.rest_api.routes.isms_routes.isms_report_helper import (
    object_reference_lookup_stages,
    risk_reference_lookup_stages,
)

from tests.utils.ipam_doc_builders import make_type_doc
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_ID: int = 99581
OBJECT_ID: int = 99582
RISK_ID: int = 99583
ASSESSMENT_ID: int = 99584
ORPHAN_ASSESSMENT_ID: int = 99585
MISSING_RISK_ID: int = 99589
TYPE_LABEL: str = 'Lookup Server'
GROUP_NAME: str = 'Lookup Group'
FIELD_VALUE: str = 'must not be joined'


@pytest.fixture(name='assessments')
def fixture_assessments(database_manager: MongoDatabaseManager, database_name: str):
    """An object (with a field), a group sharing its id, a risk, and two assessments; removed again"""
    seeds: dict[str, list[dict[str, Any]]] = {
        CmdbType.COLLECTION: [{**make_type_doc(TYPE_ID, 'isms-lookup-server'), 'label': TYPE_LABEL}],
        CmdbObject.COLLECTION: [{'public_id': OBJECT_ID, 'type_id': TYPE_ID, 'active': True, 'author_id': 1,
                                 'creation_time': datetime.now(timezone.utc),
                                 'fields': [{'name': 'dg-name', 'value': FIELD_VALUE}]}],
        CmdbObjectGroup.COLLECTION: [{'public_id': OBJECT_ID, 'name': GROUP_NAME, 'assigned': [1, 2, 3]}],
        IsmsRisk.COLLECTION: [{'public_id': RISK_ID, 'name': 'Lookup risk'}],
        IsmsRiskAssessment.COLLECTION: [
            {'public_id': ASSESSMENT_ID, 'risk_id': RISK_ID, 'object_id': OBJECT_ID, 'object_id_ref_type': 'OBJECT'},
            {'public_id': ORPHAN_ASSESSMENT_ID, 'risk_id': MISSING_RISK_ID, 'object_id': OBJECT_ID,
             'object_id_ref_type': 'OBJECT'},
        ],
    }

    def _purge() -> None:
        for collection, docs in seeds.items():
            database_manager.get_collection(collection, database_name).delete_many(
                {'public_id': {'$in': [doc['public_id'] for doc in docs]}},
            )

    _purge()
    for collection, docs in seeds.items():
        database_manager.get_collection(collection, database_name).insert_many([dict(doc) for doc in docs])

    yield database_manager.get_collection(IsmsRiskAssessment.COLLECTION, database_name)

    _purge()


def _run(assessments, public_id: int, stages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The assessment's documents after the stages"""
    return list(assessments.aggregate([Builder.match_({'public_id': public_id}), *stages]))


def test_each_join_keeps_only_the_key_the_report_reads(assessments) -> None:
    """The object brings its type_id, the group its name, the type its label - nothing else"""
    joined = _run(assessments, ASSESSMENT_ID, object_reference_lookup_stages())[0]

    assert joined[ReportAlias.OBJECT.value] == [{'type_id': TYPE_ID}]
    assert joined[ReportAlias.OBJECT_GROUP.value] == [{'name': GROUP_NAME}]
    assert joined[ReportAlias.OBJECT_TYPE.value] == [{'label': TYPE_LABEL}]


def test_an_assessment_of_a_missing_risk_is_kept(assessments) -> None:
    """The risk is preserved as absent rather than dropping the row"""
    rows = _run(assessments, ORPHAN_ASSESSMENT_ID, risk_reference_lookup_stages())

    assert len(rows) == 1
    assert ReportAlias.RISK.value not in rows[0]
    assert rows[0][ReportAlias.PROTECTION_GOALS.value] == []


def test_a_resolving_risk_is_joined(assessments) -> None:
    """The ordinary case: one risk document under 'risk'"""
    rows = _run(assessments, ASSESSMENT_ID, risk_reference_lookup_stages())

    assert rows[0][ReportAlias.RISK.value]['name'] == 'Lookup risk'
