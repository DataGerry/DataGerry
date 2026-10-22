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
Integration tests for the narrowed managers against a real MongoDB: the failures they expect still become their
own errors

``ObjectsManager`` and ``GenericManager`` no longer catch everything. What they still catch has to be what a real
failure actually raises, or a database failure would slip past them as an unhandled error (the route's 500 where a
400 is meant). Nothing is patched here: MongoDB itself refuses an unknown query operator, and a stored document that
no longer fits its model fails its model's own read
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.objects_manager import ObjectsManager
from cmdb.manager.persons_manager import PersonsManager
from cmdb.manager.query_builder import BuilderParameters
from cmdb.manager.report_categories_manager import ReportCategoriesManager
from cmdb.models.person_model import CmdbPerson
from cmdb.utils import find_cause

from cmdb.errors.manager import BaseManagerGetError, BaseManagerIterationError
from cmdb.errors.manager.objects_manager import ObjectsManagerGetError, ObjectsManagerIterationError
from cmdb.errors.manager.persons_manager import PERSONS_MANAGER_ERRORS
from cmdb.errors.manager.report_categories_manager import REPORT_CATEGORIES_MANAGER_ERRORS
# -------------------------------------------------------------------------------------------------------------------- #

# A query operator MongoDB does not know - it refuses the read itself
UNKNOWN_OPERATOR_CRITERIA: dict[str, Any] = {'public_id': {'$no_such_operator': 1}}
BROKEN_PERSON_ID: int = 97201


def test_a_refused_object_read_is_the_get_error(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """find_objects: the real read's BaseManagerGetError is still wrapped as the manager's get error"""
    manager = ObjectsManager(database_manager, database_name)

    with pytest.raises(ObjectsManagerGetError) as caught:
        manager.find_objects(UNKNOWN_OPERATOR_CRITERIA)

    assert find_cause(caught.value, BaseManagerGetError) is not None


def test_a_refused_object_iteration_is_the_iteration_error(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """iterate: the real aggregation's failure, through iterate_query, is the manager's iteration error"""
    manager = ObjectsManager(database_manager, database_name)

    with pytest.raises(ObjectsManagerIterationError) as caught:
        manager.iterate(BuilderParameters(criteria=UNKNOWN_OPERATOR_CRITERIA))

    assert find_cause(caught.value, BaseManagerIterationError) is not None


def test_a_refused_generic_iteration_is_the_managers_error(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """GenericManager.iterate_items, on a real subclass: the configured 'iterate' error"""
    manager = ReportCategoriesManager(database_manager, database_name)

    with pytest.raises(REPORT_CATEGORIES_MANAGER_ERRORS['iterate']) as caught:
        manager.iterate_items(BuilderParameters(criteria=UNKNOWN_OPERATOR_CRITERIA))

    assert find_cause(caught.value, BaseManagerIterationError) is not None


def test_a_stored_document_that_no_longer_fits_its_model_is_the_get_error(
        database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    GenericManager.get_item: the model's declared deserialisation error is still the configured 'get' error

    A person stored without the keys its model requires - a drifted document, not a bug in the code
    """
    persons = database_manager.get_collection(CmdbPerson.COLLECTION, database_name)
    persons.delete_many({'public_id': BROKEN_PERSON_ID})
    persons.insert_one({'public_id': BROKEN_PERSON_ID})

    try:
        with pytest.raises(PERSONS_MANAGER_ERRORS['get']) as caught:
            PersonsManager(database_manager, database_name).get_item(BROKEN_PERSON_ID)

        assert find_cause(caught.value, CmdbPerson.INIT_FROM_DATA_ERROR) is not None
    finally:
        persons.delete_many({'public_id': BROKEN_PERSON_ID})
