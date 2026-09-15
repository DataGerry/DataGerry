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
Functional tests for the CABLE SpecialType over the REST routes

Covers what the pure blueprint tests cannot: that the creation dialog's routes actually offer CABLE
and serve its blueprint, and - the part with real behaviour behind it - that the cable-type select is
seeded from the CABLE_TYPE options that are IN THE DATABASE at the moment the schema is fetched.

That seeding is the one place where a pure blueprint meets stored data. get_cable_schema takes the
values as an argument, so the route has to read them; a route that forgot to would still serve a valid
schema, just with an empty select, and no unit test of either half would notice. These tests are where
the two halves are measured together.

The Cable CI is gated behind LicenseFeature.IPAM by design decision D6, which is why the type write
needs the feature unlocked here
"""
from datetime import datetime, timezone
from http import HTTPStatus
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.extendable_option_model import CmdbExtendableOption, ExtendableOptionKey, OptionType
from cmdb.models.type_model import CmdbType, FieldKey, TypeSchemaKey
from cmdb.models.special_type_model.special_type_enum import SpecialType
from cmdb.models.special_type_model.cable_constants import CableField, CableSection
from cmdb.security.license.license_constants import LicenseFeature
# -------------------------------------------------------------------------------------------------------------------- #


@pytest.fixture(autouse=True)
def _ipam_licensed(monkeypatch: pytest.MonkeyPatch):
    """Licenses IPAM so the gated Cable surface is reachable.

    Port Connectivity is gated behind LicenseFeature.IPAM in full (decision D6), and CABLE is in
    SpecialType.get_license_gated_types, so the CmdbType write needs the feature unlocked here.
    """
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.IPAM)

SPECIAL_TYPES_URL: str = '/special_types'
TYPES_URL: str = '/types'

CABLE_LABEL: str = 'Port Connectivity - Cable class'

CABLE_TYPE_ID: int = 9711
ALL_TYPE_IDS: list[int] = [CABLE_TYPE_ID]

SEED_AUTHOR_ID: int = 1
SEED_VERSION: str = '1.0.0'

# Option public_ids well outside anything else the suite seeds
OPTION_IDS: list[int] = [9721, 9722, 9723]
PREDEFINED_VALUES: list[str] = ['Cat6a', 'OM4']
CUSTOMER_VALUE: str = 'Cat8.1 (in-house)'


def _types_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the CmdbType collection of the test database"""
    return database_manager.get_collection(CmdbType.COLLECTION, database_name)


def _options_collection(database_manager: MongoDatabaseManager, database_name: str):
    """Returns the CmdbExtendableOption collection of the test database"""
    return database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)


def _option_doc(public_id: int, value: str, predefined: bool = True) -> dict[str, Any]:
    """A stored CABLE_TYPE CmdbExtendableOption"""
    return {
        ExtendableOptionKey.PUBLIC_ID.value: public_id,
        ExtendableOptionKey.VALUE.value: value,
        ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value,
        ExtendableOptionKey.PREDEFINED.value: predefined,
    }


@pytest.fixture(autouse=True)
def _clean_cable_data(database_manager: MongoDatabaseManager, database_name: str):
    """
    Removes the seeded Cable type and CABLE_TYPE options before and after each test

    A SpecialType may exist only once per installation, so a leftover Cable type from one test would
    make the next one's creation fail - and would also hide CABLE from the ?available=true listing.
    The options are cleared too because every assertion below is about which values reach the select.
    """
    types = _types_collection(database_manager, database_name)
    options = _options_collection(database_manager, database_name)

    types.delete_many({ExtendableOptionKey.PUBLIC_ID.value: {'$in': ALL_TYPE_IDS}})
    options.delete_many({ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value})

    yield

    types.delete_many({ExtendableOptionKey.PUBLIC_ID.value: {'$in': ALL_TYPE_IDS}})
    options.delete_many({ExtendableOptionKey.OPTION_TYPE.value: OptionType.CABLE_TYPE.value})


def _seed_cable_type_options(
        database_manager: MongoDatabaseManager, database_name: str, values: list[str]) -> None:
    """Seeds CABLE_TYPE options in the given order, using ascending public_ids"""
    _options_collection(database_manager, database_name).insert_many([
        _option_doc(OPTION_IDS[index], value) for index, value in enumerate(values)
    ])


def _fetch_cable_schema(rest_api) -> dict[str, Any]:
    """Fetches the CABLE blueprint the way the creation dialog does"""
    response = rest_api.get(f'{SPECIAL_TYPES_URL}/schema?special_type={SpecialType.CABLE.value}')

    assert response.status_code == HTTPStatus.OK

    return response.get_json()


def _cable_type_options(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Reads the cable-type select's inline options out of a fetched blueprint"""
    cable_type = next(
        field for field in schema[TypeSchemaKey.FIELDS.value]
        if field[FieldKey.NAME.value] == CableField.TYPE.value
    )

    return cable_type[FieldKey.OPTIONS.value]


def _cable_type_payload(public_id: int, cable_type_options: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Builds a Cable CmdbType payload as the frontend would send it after fetching the blueprint

    The blueprint supplies the fields, their options and the section; the identity, label, icon and
    summary come from the creating user.
    """
    return {
        'public_id': public_id,
        'name': f'cable-{public_id}',
        'label': 'Cable',
        'author_id': SEED_AUTHOR_ID,
        'active': True,
        TypeSchemaKey.SPECIAL_TYPE.value: SpecialType.CABLE.value,
        'fields': [
            {'type': 'text', 'name': CableField.NAME.value, 'label': 'Cable name', 'required': True},
            {'type': 'select', 'name': CableField.TYPE.value, 'label': 'Cable type',
             'options': cable_type_options},
            {'type': 'text', 'name': CableField.LENGTH.value, 'label': 'Length'},
            {'type': 'text', 'name': CableField.COLOR.value, 'label': 'Color'},
            {'type': 'textarea', 'name': CableField.DESCRIPTION.value, 'label': 'Description'},
        ],
        'render_meta': {
            'icon': 'fas fa-plug',
            'sections': [{
                'type': 'section',
                'name': CableSection.INFORMATION.value,
                'label': 'Information',
                'fields': [
                    CableField.NAME.value,
                    CableField.TYPE.value,
                    CableField.LENGTH.value,
                    CableField.COLOR.value,
                    CableField.DESCRIPTION.value,
                ],
            }],
            'summary': {'fields': [CableField.NAME.value]},
        },
        'acl': {'activated': False, 'groups': {'includes': None}},
        'version': SEED_VERSION,
    }


def _insert_cable_type(database_manager: MongoDatabaseManager, database_name: str, public_id: int) -> None:
    """Inserts a Cable CmdbType directly, bypassing the POST route's validation"""
    doc = _cable_type_payload(public_id, [])
    doc['creation_time'] = datetime.now(timezone.utc)
    _types_collection(database_manager, database_name).insert_one(doc)


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the creation dialog's routes                                              #
# -------------------------------------------------------------------------------------------------------------------- #
class TestSpecialTypeListing:
    """GET /special_types/ offers CABLE, and stops offering it once one exists"""

    def test_listing_includes_cable_with_its_label(self, rest_api) -> None:
        """The full listing carries the CABLE token and its display label"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json()[SpecialType.CABLE.value] == CABLE_LABEL

    def test_available_listing_offers_cable_while_unclaimed(self, rest_api) -> None:
        """With no Cable type in the database, CABLE is offered by the creation dialog"""
        response = rest_api.get(f'{SPECIAL_TYPES_URL}/?available=true')

        assert response.status_code == HTTPStatus.OK
        assert SpecialType.CABLE.value in response.get_json()

    def test_available_listing_drops_cable_once_claimed(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """A SpecialType exists at most once, so an existing Cable type removes it from the offer"""
        _insert_cable_type(database_manager, database_name, CABLE_TYPE_ID)

        response = rest_api.get(f'{SPECIAL_TYPES_URL}/?available=true')

        assert response.status_code == HTTPStatus.OK
        assert SpecialType.CABLE.value not in response.get_json()


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the CABLE blueprint                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCableSchemaRoute:
    """GET /special_types/schema serves the CABLE blueprint the dialog builds the type from"""

    def test_the_route_serves_the_cable_blueprint(self, rest_api) -> None:
        """The blueprint arrives marked as CABLE, with all five fields and the single section"""
        schema = _fetch_cable_schema(rest_api)

        assert schema[TypeSchemaKey.SPECIAL_TYPE.value] == SpecialType.CABLE.value
        assert [field[FieldKey.NAME.value] for field in schema[TypeSchemaKey.FIELDS.value]] == [
            CableField.NAME.value,
            CableField.TYPE.value,
            CableField.LENGTH.value,
            CableField.COLOR.value,
            CableField.DESCRIPTION.value,
        ]
        assert len(schema[TypeSchemaKey.SECTIONS.value]) == 1
        assert schema[TypeSchemaKey.SECTIONS.value][0]['name'] == CableSection.INFORMATION.value

    def test_the_cable_type_select_is_seeded_from_the_stored_options(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        The half no pure test can cover: the route really reads the option list

        get_cable_schema takes the values as an argument, so a route that forgot to read them would
        still serve a perfectly valid schema - with an empty select nobody could pick a cable type
        from.
        """
        _seed_cable_type_options(database_manager, database_name, PREDEFINED_VALUES)

        options = _cable_type_options(_fetch_cable_schema(rest_api))

        assert [option['name'] for option in options] == PREDEFINED_VALUES

    def test_a_customer_added_value_reaches_the_select(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        Every CABLE_TYPE option that exists is snapshotted, not only the predefined ones

        A customer who already extended the list gets their own values in the type they create.
        """
        _seed_cable_type_options(
            database_manager, database_name, PREDEFINED_VALUES + [CUSTOMER_VALUE],
        )

        options = _cable_type_options(_fetch_cable_schema(rest_api))

        assert CUSTOMER_VALUE in [option['name'] for option in options]

    def test_an_empty_option_list_yields_an_empty_select(self, rest_api) -> None:
        """
        A customer may have deleted every CABLE_TYPE option

        The blueprint is served with an empty select rather than refused, or silently back-filled
        from the predefined values - those stay deletable until connections reference them.
        """
        assert _cable_type_options(_fetch_cable_schema(rest_api)) == []

    def test_the_select_carries_no_option_type_key(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        A stored CmdbType field has no 'option_type' key, which is why the values are inlined

        The type schema does not list it, so Validator(purge_unknown=True) would drop it silently -
        the select would then offer nothing at all after the type was saved.
        """
        _seed_cable_type_options(database_manager, database_name, PREDEFINED_VALUES)

        cable_type = next(
            field for field in _fetch_cable_schema(rest_api)[TypeSchemaKey.FIELDS.value]
            if field[FieldKey.NAME.value] == CableField.TYPE.value
        )

        assert FieldKey.OPTION_TYPE.value not in cable_type


# -------------------------------------------------------------------------------------------------------------------- #
#                                              creating a Cable type                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
class TestCreateCableType:
    """POST /types/ creates the Cable type from the blueprint the dialog fetched"""

    def test_creates_the_cable_type_with_its_seeded_options(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """
        End to end: fetch the blueprint, post the type, read the stored options back

        This is the round trip that proves the snapshot survives the type write - the select's inline
        options have to come back out of the stored CmdbType, since nothing else remembers them.
        """
        _seed_cable_type_options(database_manager, database_name, PREDEFINED_VALUES)

        options = _cable_type_options(_fetch_cable_schema(rest_api))
        response = rest_api.post(f'{TYPES_URL}/', json=_cable_type_payload(CABLE_TYPE_ID, options))

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)

        stored = _types_collection(database_manager, database_name).find_one(
            {ExtendableOptionKey.PUBLIC_ID.value: CABLE_TYPE_ID},
        )
        stored_cable_type = next(
            field for field in stored['fields'] if field['name'] == CableField.TYPE.value
        )

        assert [option['name'] for option in stored_cable_type['options']] == PREDEFINED_VALUES

    def test_the_stored_type_carries_the_cable_marker(
        self,
        rest_api,
        database_manager: MongoDatabaseManager,
        database_name: str,
    ) -> None:
        """The marker is what claims the SpecialType and what cable_ci_id validation reads"""
        rest_api.post(f'{TYPES_URL}/', json=_cable_type_payload(CABLE_TYPE_ID, []))

        stored = _types_collection(database_manager, database_name).find_one(
            {ExtendableOptionKey.PUBLIC_ID.value: CABLE_TYPE_ID},
        )

        assert stored[TypeSchemaKey.SPECIAL_TYPE.value] == SpecialType.CABLE.value
