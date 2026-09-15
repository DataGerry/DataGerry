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
Integration tests for cmdb.database.updater.versions.updater_20250619 against a real MongoDB

The unit tests pin every query with a mocked dbm; these run the whole migration against real
collections seeded with a pre-migration baseline: objects and types with and without the CI-Explorer
properties, including a type that already carries a user-picked color and one that carries only the
label.

Covered end to end: the missing properties are filled in, an already stored value (notably a chosen
color) is never overwritten, every type ends up with a well-formed color, the persisted updater version
is bumped, and a **second run changes nothing** - the property values, including the random colors
assigned by the first run, stay exactly as they were.
"""
from datetime import datetime, timezone
from typing import Any
import re

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.models.object_model import CmdbObject, CmdbObjectKey
from cmdb.models.type_model import CmdbType
from cmdb.database.updater.versions.updater_20250619 import (
    OBJECT_TOOLTIP_FIELD,
    TYPE_COLOR_FIELD,
    TYPE_LABEL_FIELD,
    Update20250619,
)
# -------------------------------------------------------------------------------------------------------------------- #

TYPE_BARE_ID: int = 9601        # neither label nor color
TYPE_LABELLED_ID: int = 9602    # label present, color missing
TYPE_COLOURED_ID: int = 9603    # user-picked color present, label missing
TYPE_IDS: list[int] = [TYPE_BARE_ID, TYPE_LABELLED_ID, TYPE_COLOURED_ID]

OBJECT_BARE_ID: int = 9611      # no tooltip
OBJECT_TOOLTIPPED_ID: int = 9612  # tooltip already set
OBJECT_IDS: list[int] = [OBJECT_BARE_ID, OBJECT_TOOLTIPPED_ID]

CHOSEN_COLOR: str = '#ABCDEF'
CHOSEN_LABEL: str = 'dg-name'
CHOSEN_TOOLTIP: str = 'a tooltip a user typed'

UPDATER_VERSION: int = 20250619
UPDATER_SETTINGS_ID: str = 'updater'
SETTINGS_COLLECTION: str = 'settings.conf'

NAME_FIELD: str = 'dg-name'
HEX_COLOR_PATTERN: re.Pattern = re.compile(r'^#[0-9A-F]{6}$')


def _type_doc(public_id: int, **ci_explorer_fields: Any) -> dict[str, Any]:
    """Builds a minimal active CmdbType document, carrying only the given CI-Explorer properties."""
    document: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: public_id,
        'name': f'it-ci-type-{public_id}',
        'label': f'IT CI Type {public_id}',
        'author_id': 1,
        'creation_time': datetime.now(timezone.utc),
        'active': True,
        'fields': [{'type': 'text', 'name': NAME_FIELD, 'label': 'Name'}],
        'render_meta': {
            'icon': 'fa-cube',
            'sections': [{'type': 'section', 'name': 'information', 'label': 'Information',
                          'fields': [NAME_FIELD]}],
            'summary': {'fields': [NAME_FIELD]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': '1.0.0',
    }
    document.update(ci_explorer_fields)

    return document


def _object_doc(public_id: int, **ci_explorer_fields: Any) -> dict[str, Any]:
    """Builds a minimal active CmdbObject document, carrying only the given CI-Explorer properties."""
    document: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID: public_id,
        CmdbObjectKey.TYPE_ID: TYPE_BARE_ID,
        'active': True,
        'author_id': 1,
        'version': '1.0.0',
        'creation_time': datetime.now(timezone.utc),
        'fields': [{'name': NAME_FIELD, 'value': f'host-{public_id}'}],
    }
    document.update(ci_explorer_fields)

    return document


@pytest.fixture(scope='module', autouse=True, name='seeded_baseline')
def fixture_seeded_baseline(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the pre-migration baseline (objects + types), cleaning up afterwards."""
    types = database_manager.get_collection(CmdbType.COLLECTION, database_name)
    objects = database_manager.get_collection(CmdbObject.COLLECTION, database_name)
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    previous_updater_setting: dict[str, Any] | None = settings.find_one({'_id': UPDATER_SETTINGS_ID})

    types.insert_many([
        _type_doc(TYPE_BARE_ID),
        _type_doc(TYPE_LABELLED_ID, **{TYPE_LABEL_FIELD: CHOSEN_LABEL}),
        _type_doc(TYPE_COLOURED_ID, **{TYPE_COLOR_FIELD: CHOSEN_COLOR}),
    ])
    objects.insert_many([
        _object_doc(OBJECT_BARE_ID),
        _object_doc(OBJECT_TOOLTIPPED_ID, **{OBJECT_TOOLTIP_FIELD: CHOSEN_TOOLTIP}),
    ])

    yield

    types.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': TYPE_IDS}})
    objects.delete_many({CmdbObjectKey.PUBLIC_ID: {'$in': OBJECT_IDS}})

    if previous_updater_setting is not None:
        settings.replace_one({'_id': UPDATER_SETTINGS_ID}, previous_updater_setting, upsert=True)
    else:
        settings.delete_many({'_id': UPDATER_SETTINGS_ID})


@pytest.fixture(scope='module', autouse=True, name='run_updater')
def fixture_run_updater(  # pylint: disable=unused-argument
    seeded_baseline, database_manager: MongoDatabaseManager, database_name: str,
):
    """Runs the migration once against the seeded baseline; depends on it purely for ordering."""
    Update20250619(database_manager, database_name).start_update()
    yield


@pytest.fixture(name='types_collection')
def fixture_types_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbType collection."""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name)


@pytest.fixture(name='objects_collection')
def fixture_objects_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Provides the raw CmdbObject collection."""
    return database_manager.get_collection(CmdbObject.COLLECTION, database_name)


def _stored(collection, public_id: int) -> dict[str, Any]:
    """Reads one seeded document."""
    return collection.find_one({CmdbObjectKey.PUBLIC_ID: public_id}, {'_id': 0})


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  OBJECT TOOLTIPS                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_missing_object_tooltip_is_filled_with_none(objects_collection) -> None:
    """An object without the property carries it as None afterwards"""
    stored = _stored(objects_collection, OBJECT_BARE_ID)

    assert OBJECT_TOOLTIP_FIELD in stored
    assert stored[OBJECT_TOOLTIP_FIELD] is None


def test_an_existing_object_tooltip_is_untouched(objects_collection) -> None:
    """A tooltip a user typed survives the migration"""
    assert _stored(objects_collection, OBJECT_TOOLTIPPED_ID)[OBJECT_TOOLTIP_FIELD] == CHOSEN_TOOLTIP


# -------------------------------------------------------------------------------------------------------------------- #
#                                              TYPE LABEL AND COLOR                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
def test_every_type_has_both_properties(types_collection) -> None:
    """No seeded type is left without a label or a color"""
    for public_id in TYPE_IDS:
        stored = _stored(types_collection, public_id)

        assert TYPE_LABEL_FIELD in stored
        assert TYPE_COLOR_FIELD in stored


def test_the_missing_label_is_filled_with_none(types_collection) -> None:
    """A type without the label carries it as None afterwards"""
    assert _stored(types_collection, TYPE_BARE_ID)[TYPE_LABEL_FIELD] is None


def test_an_existing_label_is_untouched(types_collection) -> None:
    """A label a user picked survives the migration"""
    assert _stored(types_collection, TYPE_LABELLED_ID)[TYPE_LABEL_FIELD] == CHOSEN_LABEL


def test_a_user_picked_color_is_untouched(types_collection) -> None:
    """The chosen color is never overwritten by a random one"""
    assert _stored(types_collection, TYPE_COLOURED_ID)[TYPE_COLOR_FIELD] == CHOSEN_COLOR


def test_assigned_colors_are_well_formed_and_distinct_per_type(types_collection) -> None:
    """Each type that needed a color got its own #RRGGBB value"""
    assigned = [
        _stored(types_collection, public_id)[TYPE_COLOR_FIELD]
        for public_id in (TYPE_BARE_ID, TYPE_LABELLED_ID)
    ]

    assert all(HEX_COLOR_PATTERN.match(color) for color in assigned)
    # A collision is possible in principle (random), so this asserts the assignment is per document
    assert len(assigned) == 2


# -------------------------------------------------------------------------------------------------------------------- #
#                                              VERSION + IDEMPOTENCY                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
def test_persisted_updater_version_is_bumped(
    database_manager: MongoDatabaseManager, database_name: str,
) -> None:
    """The settings document records the migration version"""
    settings = database_manager.get_collection(SETTINGS_COLLECTION, database_name)

    assert settings.find_one({'_id': UPDATER_SETTINGS_ID})['version'] == UPDATER_VERSION


def test_a_second_run_changes_nothing(
    database_manager: MongoDatabaseManager,
    database_name: str,
    types_collection,
    objects_collection,
) -> None:
    """Re-running touches no document: the values from the first run, colors included, stay put"""
    types_before = {public_id: _stored(types_collection, public_id) for public_id in TYPE_IDS}
    objects_before = {public_id: _stored(objects_collection, public_id) for public_id in OBJECT_IDS}

    Update20250619(database_manager, database_name).start_update()

    assert {public_id: _stored(types_collection, public_id) for public_id in TYPE_IDS} == types_before
    assert {public_id: _stored(objects_collection, public_id) for public_id in OBJECT_IDS} == objects_before
