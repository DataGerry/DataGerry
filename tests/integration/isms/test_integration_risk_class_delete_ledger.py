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
Integration tests: the RiskClass delete's writes undone together against a real MongoDB

The route records the class delete and the RiskMatrix clean-up on one ledger (`remove_deleted_risk_class_from_matrix`
with the ledger). Here the same steps run on the real managers and the ledger is undone: the class document and the
grid come back exactly as they were, and a second undo changes nothing
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.write_ledger import WriteLedger
from cmdb.manager import RiskClassManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.group_model.group_constants import ADMIN_GROUP_ID
from cmdb.models.isms_model import IsmsRiskClass, IsmsRiskMatrix
from cmdb.models.isms_model.isms_helper import remove_deleted_risk_class_from_matrix
from cmdb.models.isms_model.isms_risk_matrix_constants import RISK_MATRIX_PUBLIC_ID
from cmdb.models.user_model import CmdbUser
# -------------------------------------------------------------------------------------------------------------------- #

pytestmark = pytest.mark.usefixtures('rest_api_app_context')

RISK_CLASS_ID: int = 97961
OTHER_RISK_CLASS_ID: int = 97962
ADMINISTRATOR: CmdbUser = CmdbUser(public_id=1, user_name='admin', active=True, group_id=ADMIN_GROUP_ID)


@pytest.fixture(name='stored')
def fixture_stored(database_manager: MongoDatabaseManager, database_name: str):
    """A class, and a grid with a cell naming it and one naming another class; both put back afterwards"""
    risk_classes = database_manager.get_collection(IsmsRiskClass.COLLECTION, database_name)
    matrices = database_manager.get_collection(IsmsRiskMatrix.COLLECTION, database_name)
    stored_matrix: dict[str, Any] | None = matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID})
    risk_classes.delete_many({'public_id': RISK_CLASS_ID})
    risk_classes.insert_one({'public_id': RISK_CLASS_ID, 'name': 'ledger-class', 'color': '#aabbcc'})
    matrices.update_one({'public_id': RISK_MATRIX_PUBLIC_ID}, {'$set': {'risk_matrix': [
        {'impact_id': 1, 'likelihood_id': 1, 'calculated_value': 1.0, 'risk_class_id': RISK_CLASS_ID},
        {'impact_id': 1, 'likelihood_id': 2, 'calculated_value': 2.0, 'risk_class_id': OTHER_RISK_CLASS_ID},
    ], 'matrix_unit': None}}, upsert=True)

    def _state() -> tuple[Any, Any]:
        """The class and the grid as stored"""
        return (risk_classes.find_one({'public_id': RISK_CLASS_ID}, {'_id': 0}),
                matrices.find_one({'public_id': RISK_MATRIX_PUBLIC_ID}, {'_id': 0}))

    yield _state

    risk_classes.delete_many({'public_id': RISK_CLASS_ID})
    matrices.delete_many({'public_id': RISK_MATRIX_PUBLIC_ID})
    if stored_matrix is not None:
        matrices.insert_one(stored_matrix)


def _delete_on(ledger: WriteLedger) -> None:
    """The route's two steps: the class delete recorded once it deleted, then the matrix clean-up"""
    risk_class_manager: RiskClassManager = ManagerProvider.get_manager(ManagerType.RISK_CLASS, ADMINISTRATOR)
    snapshot: dict[str, Any] = risk_class_manager.get_item(RISK_CLASS_ID, as_dict=True)

    if risk_class_manager.delete_item(RISK_CLASS_ID):
        ledger.deleted(risk_class_manager, RISK_CLASS_ID, snapshot)

    remove_deleted_risk_class_from_matrix(RISK_CLASS_ID, ADMINISTRATOR, ledger)


def test_the_steps_write_what_the_route_promises(stored) -> None:
    """The class gone, only its own cell reset"""
    _delete_on(WriteLedger())

    risk_class, matrix = stored()
    assert risk_class is None
    assert [cell['risk_class_id'] for cell in matrix['risk_matrix']] == [0, OTHER_RISK_CLASS_ID]


def test_the_undo_puts_back_the_class_and_the_grid(stored) -> None:
    """Exactly as before - the class document and every cell"""
    before = stored()
    ledger = WriteLedger()
    _delete_on(ledger)

    assert not ledger.undo()
    assert stored() == before


def test_a_second_undo_changes_nothing(stored) -> None:
    """Re-run safe: the state the first undo restored stays"""
    before = stored()
    ledger = WriteLedger()
    _delete_on(ledger)
    ledger.undo()

    ledger.undo()

    assert stored() == before
