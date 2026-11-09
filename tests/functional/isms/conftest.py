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
Shared fixtures of the ISMS functional tests

Every test here may send a body naming a seeded option (implementation state, source, Risk category) or assessing the
seeded object group (``tests.utils.isms_reference_seed``): the write routes refuse an option that is not of its field's
list and an assessed group that is not stored, so they are stored around each test
"""
from typing import Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from tests.utils.isms_reference_seed import (
    purge_assessed_object_group,
    purge_isms_options,
    seed_assessed_object_group,
    seed_isms_options,
)
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _isms_options(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Stores one option of each list an ISMS body draws from; removes them afterwards"""
    seed_isms_options(database_manager, database_name)
    yield
    purge_isms_options(database_manager, database_name)


@pytest.fixture(autouse=True)
def _assessed_object_group(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[None]:
    """Stores the object group the shared RiskAssessment body assesses; removes it afterwards"""
    seed_assessed_object_group(database_manager, database_name)
    yield
    purge_assessed_object_group(database_manager, database_name)
