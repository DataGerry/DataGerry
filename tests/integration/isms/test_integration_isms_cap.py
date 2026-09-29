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
Integration tests for the ISMS create caps against the real collections

``abort_if_isms_cap_reached`` counts through each bounded entity's own manager, so the cap is judged by
what that collection really holds: full is a 400, one free slot passes. Each test empties its collection
first and puts the documents it found back afterwards
"""
from http import HTTPStatus
from typing import Any, Type

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.database import MongoDatabaseManager
from cmdb.manager.generic_manager import GenericManager
from cmdb.manager.isms_manager.impact_manager import ImpactManager
from cmdb.manager.isms_manager.likelihood_manager import LikelihoodManager
from cmdb.manager.isms_manager.risk_class_manager import RiskClassManager
from cmdb.models.isms_model import IsmsImpact, IsmsLikelihood, IsmsRiskClass
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_constants import (
    ISMS_CAP_REACHED_MSG,
    ISMS_IMPACTS_LABEL,
    ISMS_LIKELIHOODS_LABEL,
    ISMS_RISK_CLASSES_LABEL,
    MAX_ISMS_RISK_CLASSES,
    MAX_ISMS_SCALE_ENTRIES,
)
from cmdb.interface.rest_api.routes.isms_routes.isms_routes_helper import abort_if_isms_cap_reached
# -------------------------------------------------------------------------------------------------------------------- #

FIRST_SEED_ID: int = 97951

CAPPED_ENTITIES: list[tuple[Type[GenericManager], str, int, str]] = [
    (LikelihoodManager, IsmsLikelihood.COLLECTION, MAX_ISMS_SCALE_ENTRIES, ISMS_LIKELIHOODS_LABEL),
    (ImpactManager, IsmsImpact.COLLECTION, MAX_ISMS_SCALE_ENTRIES, ISMS_IMPACTS_LABEL),
    (RiskClassManager, IsmsRiskClass.COLLECTION, MAX_ISMS_RISK_CLASSES, ISMS_RISK_CLASSES_LABEL),
]
ENTITY_IDS: list[str] = ['likelihoods', 'impacts', 'risk-classes']


@pytest.fixture(name='emptied', params=CAPPED_ENTITIES, ids=ENTITY_IDS)
def fixture_emptied(request, database_manager: MongoDatabaseManager, database_name: str):
    """Yields (manager, collection, cap, label) with the collection emptied; restores it afterwards."""
    manager_class, collection_name, cap, label = request.param
    collection = database_manager.get_collection(collection_name, database_name)
    kept: list[dict[str, Any]] = list(collection.find({}))
    collection.delete_many({})

    yield manager_class(database_manager), collection, cap, label

    collection.delete_many({})
    if kept:
        collection.insert_many(kept)


def _seed(collection, count: int) -> None:
    """Stores ``count`` minimal documents."""
    if count:
        collection.insert_many([{'public_id': FIRST_SEED_ID + index} for index in range(count)])


def test_a_full_collection_refuses_the_create(emptied) -> None:
    """The cap counts what the collection really holds"""
    manager, collection, cap, label = emptied
    _seed(collection, cap)

    with pytest.raises(HTTPException) as exc_info:
        abort_if_isms_cap_reached(manager, cap, label)

    assert exc_info.value.code == HTTPStatus.BAD_REQUEST
    assert exc_info.value.description == ISMS_CAP_REACHED_MSG.format(cap=cap, entity_label=label)


def test_the_last_free_slot_passes(emptied) -> None:
    """One below the cap"""
    manager, collection, cap, label = emptied
    _seed(collection, cap - 1)

    abort_if_isms_cap_reached(manager, cap, label)  # must not raise
