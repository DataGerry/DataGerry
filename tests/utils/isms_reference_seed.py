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
The references an ISMS write body names that the write routes resolve: implementation states and ImpactCategories

* IMPLEMENTATION_STATE_ID - an option of the IMPLEMENTATION_STATE list. A RiskAssessment, a ControlMeasureAssignment
  and a ControlMeasure write refuse a state that is no option of that list, so a body naming a state needs it stored
* OTHER_LIST_OPTION_ID - an option of another list (RISK), which a state may not name - and the category a Risk body
  names (``RISK_CATEGORY_OPTION_ID``)
* THREAT_VULNERABILITY_SOURCE_ID / CONTROL_MEASURE_SOURCE_ID - the sources a Threat / Vulnerability / ControlMeasure
  body names (each write refuses a source that is no option of its own list)
* IMPACT_CATEGORY_IDS - ImpactCategories a risk-calculation ``impacts`` row may rate
* ASSESSED_OBJECT_GROUP_ID - the CmdbObjectGroup the shared RiskAssessment body assesses. A RiskAssessment write
  refuses an assessed object or group that is not stored, so the body's group has to be

Each kind has its own seed / purge pair: the ISMS functional conftest stores the options and the assessed group around
every test, the ImpactCategories only a test that rates one stores - a list or cap test counts them. Everything is
written straight into the collections (upserted, so a crashed earlier run is no obstacle) and removed by id
"""
from cmdb.database import MongoDatabaseManager
from cmdb.models.extendable_option_model import CmdbExtendableOption
from cmdb.models.extendable_option_model.option_type_enum import OptionType
from cmdb.models.isms_model import IsmsImpactCategory
from cmdb.models.object_group_model.cmdb_object_group import CmdbObjectGroup
# -------------------------------------------------------------------------------------------------------------------- #

IMPLEMENTATION_STATE_ID: int = 99961
IMPLEMENTATION_STATE_VALUE: str = 'Seeded implementation state'
OTHER_LIST_OPTION_ID: int = 99962
OTHER_LIST_OPTION_VALUE: str = 'Seeded risk category'
# The RISK option above doubles as the category a Risk body names
RISK_CATEGORY_OPTION_ID: int = OTHER_LIST_OPTION_ID
THREAT_VULNERABILITY_SOURCE_ID: int = 99965
CONTROL_MEASURE_SOURCE_ID: int = 99966
# An id no option carries
MISSING_OPTION_ID: int = 99969

IMPACT_CATEGORY_IDS: tuple[int, ...] = (99963, 99964)
# An id no ImpactCategory carries
MISSING_IMPACT_CATEGORY_ID: int = 99968

ASSESSED_OBJECT_GROUP_ID: int = 99270
ASSESSED_OBJECT_GROUP_NAME: str = 'Enrichment Group'

_OPTIONS: tuple[tuple[int, str, OptionType], ...] = (
    (IMPLEMENTATION_STATE_ID, IMPLEMENTATION_STATE_VALUE, OptionType.IMPLEMENTATION_STATE),
    (OTHER_LIST_OPTION_ID, OTHER_LIST_OPTION_VALUE, OptionType.RISK),
    (THREAT_VULNERABILITY_SOURCE_ID, 'Seeded threat / vulnerability source', OptionType.THREAT_VULNERABILITY),
    (CONTROL_MEASURE_SOURCE_ID, 'Seeded control measure source', OptionType.CONTROL_MEASURE),
)


def seed_isms_options(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Stores one option of each list an ISMS body draws from: the implementation state, the RISK category (also the
    "other list" option a state may not name) and the two sources

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)

    for public_id, value, option_type in _OPTIONS:
        options.replace_one(
            {'public_id': public_id},
            {'public_id': public_id, 'value': value, 'option_type': option_type.value, 'predefined': False},
            upsert=True,
        )


def purge_isms_options(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Removes what seed_isms_options stored

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': [public_id for public_id, _value, _type in _OPTIONS]}})


def seed_impact_categories(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Stores the ImpactCategories of IMPACT_CATEGORY_IDS

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    categories = database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)

    for position, category_id in enumerate(IMPACT_CATEGORY_IDS):
        categories.replace_one(
            {'public_id': category_id},
            {'public_id': category_id, 'name': f'Seeded category {category_id}', 'impact_descriptions': [],
             'sort': position},
            upsert=True,
        )


def purge_impact_categories(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Removes what seed_impact_categories stored

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    database_manager.get_collection(IsmsImpactCategory.COLLECTION, database_name)\
        .delete_many({'public_id': {'$in': list(IMPACT_CATEGORY_IDS)}})


def seed_assessed_object_group(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Stores the CmdbObjectGroup of ASSESSED_OBJECT_GROUP_ID

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name).replace_one(
        {'public_id': ASSESSED_OBJECT_GROUP_ID},
        {'public_id': ASSESSED_OBJECT_GROUP_ID, 'name': ASSESSED_OBJECT_GROUP_NAME},
        upsert=True,
    )


def purge_assessed_object_group(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """
    Removes what seed_assessed_object_group stored

    Args:
        database_manager (MongoDatabaseManager): The test database manager
        database_name (str): The test database
    """
    database_manager.get_collection(CmdbObjectGroup.COLLECTION, database_name)\
        .delete_many({'public_id': ASSESSED_OBJECT_GROUP_ID})
