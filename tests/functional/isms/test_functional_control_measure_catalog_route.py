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
Functional tests of the catalog routes of ``/isms/control_measures`` through the real REST app

Pinned: the import creates REQUIREMENT controls of the catalog (source = the option named after the catalog, state
'None'); a second import updates only the changed catalog content, keeps what the ISMS team answered, and reports the
removed identifiers as obsolete without deleting them; the status counts the controls per catalog; the catalog delete
keeps a control still assigned. ``catalog_id`` is the server's: a create drops it, an update keeps the stored one.
A body the schema refuses is a 400, a user without ``controlMeasure.add`` a 403, and a failed write a 400 that says to
import again. The routes are ISMS-license gated, so the check is stubbed
"""
from http import HTTPStatus
from typing import Any, Iterator

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.manager.isms_manager.control_measure_manager import ControlMeasureManager
from cmdb.manager.license_manager.license_service import LicenseService
from cmdb.models.extendable_option_model import CmdbExtendableOption, OptionType
from cmdb.models.group_model import CmdbUserGroup
from cmdb.models.isms_model import ControlMeasureType, IsmsControlMeasure, IsmsControlMeasureAssignment
from cmdb.models.isms_model.isms_control_measure_constants import ControlMeasureKey
from cmdb.security.license.license_constants import LicenseFeature
from cmdb.errors.manager.control_measure_manager import ControlMeasureManagerUpdateError
from cmdb.interface.rest_api.routes.isms_routes.control_measure_catalog_constants import (
    CATALOG_WRITE_FAILED_MESSAGE,
    CatalogImportKey,
    CatalogImportResultKey,
)
from tests.utils.isms_reference_seed import CONTROL_MEASURE_SOURCE_ID, IMPLEMENTATION_STATE_ID
from tests.utils.seeded_user import seeded_user
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = '/isms/control_measures'
IMPORT_URL: str = f'{ROUTE_URL}/catalog_import'
STATUS_URL: str = f'{ROUTE_URL}/catalog_status'

CATALOG_ID: str = 'test-catalog-routes'
OTHER_CATALOG_ID: str = 'test-catalog-routes-other'
CATALOG_TITLE: str = 'Test catalog of the catalog routes'
CATALOG_IDS: list[str] = [CATALOG_ID, OTHER_CATALOG_ID]

MANUAL_CM_ID: int = 98501
ASSIGNMENT_ID: int = 98550

VIEWER_GROUP_ID: int = 98560
VIEWER_ID: int = 98561
VIEWER_NAME: str = 'catalog-routes-viewer'
VIEW_RIGHT: str = 'base.isms.controlMeasure.view'

ANSWERED_REASON: str = 'answered by the ISMS team'


def _control(identifier: str, title: str, chapter: str | None = 'Chapter 1',
             description: str | None = 'Text') -> dict[str, Any]:
    """One flattened requirement of an import body"""
    return {
        ControlMeasureKey.IDENTIFIER.value: identifier,
        ControlMeasureKey.TITLE.value: title,
        ControlMeasureKey.CHAPTER.value: chapter,
        ControlMeasureKey.DESCRIPTION.value: description,
    }


def _body(controls: list[dict[str, Any]], catalog_id: str = CATALOG_ID) -> dict[str, Any]:
    """An import body"""
    return {
        ControlMeasureKey.CATALOG_ID.value: catalog_id,
        CatalogImportKey.CATALOG_TITLE.value: CATALOG_TITLE,
        CatalogImportKey.CONTROLS.value: controls,
    }


def _manual_payload() -> dict[str, Any]:
    """A valid create body of a manual control - claiming a catalog it may not set"""
    return {
        ControlMeasureKey.PUBLIC_ID.value: MANUAL_CM_ID,
        ControlMeasureKey.TITLE.value: 'Manual control',
        ControlMeasureKey.CONTROL_MEASURE_TYPE.value: ControlMeasureType.CONTROL.value,
        ControlMeasureKey.SOURCE.value: CONTROL_MEASURE_SOURCE_ID,
        ControlMeasureKey.IMPLEMENTATION_STATE.value: IMPLEMENTATION_STATE_ID,
        ControlMeasureKey.IDENTIFIER.value: 'M-1',
        ControlMeasureKey.CHAPTER.value: None,
        ControlMeasureKey.DESCRIPTION.value: None,
        ControlMeasureKey.IS_APPLICABLE.value: False,
        ControlMeasureKey.REASON.value: None,
        ControlMeasureKey.CATALOG_ID.value: CATALOG_ID,
    }


@pytest.fixture(autouse=True)
def _isms_licensed(monkeypatch: pytest.MonkeyPatch) -> None:
    """Licenses the ISMS feature so the gated routes are reachable"""
    monkeypatch.setattr(LicenseService, 'has_feature', lambda _self, feature: feature == LicenseFeature.ISMS)


@pytest.fixture(name='controls', autouse=True)
def fixture_controls(database_manager: MongoDatabaseManager, database_name: str) -> Iterator[Any]:
    """The control measures collection; every control, assignment and option a test writes removed before and after"""
    db = database_manager.connector.client[database_name]

    def _purge() -> None:
        db[IsmsControlMeasure.COLLECTION].delete_many({'$or': [
            {ControlMeasureKey.CATALOG_ID.value: {'$in': CATALOG_IDS}}, {'public_id': MANUAL_CM_ID},
        ]})
        db[IsmsControlMeasureAssignment.COLLECTION].delete_many({'public_id': ASSIGNMENT_ID})
        db[CmdbExtendableOption.COLLECTION].delete_many({'value': CATALOG_TITLE})
        db[CmdbUserGroup.COLLECTION].delete_many({'public_id': VIEWER_GROUP_ID})

    _purge()
    yield db[IsmsControlMeasure.COLLECTION]
    _purge()


def _stored(controls: Any, catalog_id: str = CATALOG_ID) -> dict[str, dict[str, Any]]:
    """The stored controls of a catalog by identifier"""
    return {doc[ControlMeasureKey.IDENTIFIER.value]: doc
            for doc in controls.find({ControlMeasureKey.CATALOG_ID.value: catalog_id}, {'_id': 0})}


def _option_id(database_manager: MongoDatabaseManager, database_name: str, option_type: OptionType,
               value: str) -> int:
    """public_id of an extendable option"""
    return database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name).find_one(
        {'option_type': option_type.value, 'value': value})['public_id']


class TestTheImport:
    """POST /isms/control_measures/catalog_import"""

    def test_a_first_import_creates_requirement_controls(self, rest_api, controls: Any,
                                                         database_manager: MongoDatabaseManager,
                                                         database_name: str) -> None:
        """Every requirement once, a REQUIREMENT of the catalog, source = the catalog's option, state 'None'"""
        response = rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One'), _control('A.2', ' Two ')]))

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {
            CatalogImportResultKey.IMPORTED.value: 2, CatalogImportResultKey.UPDATED.value: 0,
            CatalogImportResultKey.UNCHANGED.value: 0, CatalogImportResultKey.OBSOLETE.value: [],
        }
        stored = _stored(controls)
        source_id = _option_id(database_manager, database_name, OptionType.CONTROL_MEASURE, CATALOG_TITLE)
        state_id = _option_id(database_manager, database_name, OptionType.IMPLEMENTATION_STATE, 'None')
        assert stored['A.2'][ControlMeasureKey.TITLE.value] == 'Two'
        assert all(doc[ControlMeasureKey.CONTROL_MEASURE_TYPE.value] == ControlMeasureType.REQUIREMENT.value
                   and doc[ControlMeasureKey.SOURCE.value] == source_id
                   and doc[ControlMeasureKey.IMPLEMENTATION_STATE.value] == state_id
                   and doc[ControlMeasureKey.IS_APPLICABLE.value] is False
                   for doc in stored.values())

    def test_a_second_import_syncs_and_keeps_the_teams_answers(self, rest_api, controls: Any) -> None:
        """New created, changed updated (catalog content only), unchanged counted, removed reported and kept"""
        rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One'), _control('A.2', 'Two'),
                                              _control('A.3', 'Three')]))
        controls.update_one({ControlMeasureKey.IDENTIFIER.value: 'A.2', ControlMeasureKey.CATALOG_ID.value: CATALOG_ID},
                            {'$set': {ControlMeasureKey.REASON.value: ANSWERED_REASON,
                                      ControlMeasureKey.IS_APPLICABLE.value: True}})

        response = rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One'), _control('A.2', 'Two (revised)'),
                                                         _control('A.4', 'Four')]))

        assert response.get_json() == {
            CatalogImportResultKey.IMPORTED.value: 1, CatalogImportResultKey.UPDATED.value: 1,
            CatalogImportResultKey.UNCHANGED.value: 1, CatalogImportResultKey.OBSOLETE.value: ['A.3'],
        }
        stored = _stored(controls)
        assert sorted(stored) == ['A.1', 'A.2', 'A.3', 'A.4']
        assert stored['A.2'][ControlMeasureKey.TITLE.value] == 'Two (revised)'
        assert (stored['A.2'][ControlMeasureKey.REASON.value], stored['A.2'][ControlMeasureKey.IS_APPLICABLE.value]) \
            == (ANSWERED_REASON, True)

    def test_a_concurrently_created_source_option_is_reused(self, rest_api, database_manager: MongoDatabaseManager,
                                                            database_name: str, controls: Any) -> None:
        """The catalog's option already exists: no second one, the controls point at it"""
        options = database_manager.get_collection(CmdbExtendableOption.COLLECTION, database_name)
        existing_id: int = database_manager.insert(CmdbExtendableOption.COLLECTION, database_name, {
            'option_type': OptionType.CONTROL_MEASURE.value, 'value': CATALOG_TITLE, 'predefined': False,
        })

        rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One')]))

        assert options.count_documents({'value': CATALOG_TITLE}) == 1
        assert _stored(controls)['A.1'][ControlMeasureKey.SOURCE.value] == existing_id

    @pytest.mark.parametrize('body', [
        {CatalogImportKey.CATALOG_TITLE.value: CATALOG_TITLE, CatalogImportKey.CONTROLS.value: []},
        _body([{ControlMeasureKey.IDENTIFIER.value: 'A.1'}]),
        _body([_control('', 'Blank identifier')]),
    ], ids=['no-catalog-id', 'control-without-title', 'blank-identifier'])
    def test_a_body_the_schema_refuses_is_a_400(self, rest_api, controls: Any, body: dict[str, Any]) -> None:
        """Nothing written"""
        assert rest_api.post(IMPORT_URL, json=body).status_code == HTTPStatus.BAD_REQUEST
        assert not _stored(controls)

    def test_a_user_without_the_add_right_is_a_403(self, rest_api, controls: Any,
                                                   database_manager: MongoDatabaseManager,
                                                   database_name: str) -> None:
        """controlMeasure.view reads the status, but may not import"""
        controls.database[CmdbUserGroup.COLLECTION].insert_one({
            'public_id': VIEWER_GROUP_ID, 'name': VIEWER_NAME, 'label': VIEWER_NAME, 'rights': [VIEW_RIGHT],
        })

        with seeded_user(database_manager, database_name, VIEWER_ID, VIEWER_NAME, VIEWER_GROUP_ID) as viewer:
            assert rest_api.get(STATUS_URL, user=viewer).status_code == HTTPStatus.OK
            response = rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One')]), user=viewer)

        assert response.status_code == HTTPStatus.FORBIDDEN
        assert not _stored(controls)

    def test_a_failed_write_is_a_400_that_says_to_import_again(self, rest_api, monkeypatch: pytest.MonkeyPatch,
                                                               controls: Any) -> None:
        """The inserts happened, the update failed: 400, and a second import finishes the sync"""
        rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One')]))

        def _failing(*_args: Any, **_kwargs: Any) -> None:
            raise ControlMeasureManagerUpdateError('bulk write failed')

        with monkeypatch.context() as patched:
            patched.setattr(ControlMeasureManager, 'update_catalog_fields', _failing)
            response = rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One (revised)'),
                                                             _control('A.2', 'Two')]))

        assert response.status_code == HTTPStatus.BAD_REQUEST
        assert response.get_json()['message'] == CATALOG_WRITE_FAILED_MESSAGE

        again = rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One (revised)'), _control('A.2', 'Two')]))

        assert again.get_json()[CatalogImportResultKey.UPDATED.value] == 1
        assert _stored(controls)['A.1'][ControlMeasureKey.TITLE.value] == 'One (revised)'


class TestTheCatalogIdIsTheServers:
    """A create drops a client catalog_id; an update keeps the stored one"""

    def test_a_create_drops_the_catalog_id(self, rest_api, controls: Any) -> None:
        """A manual control claims a catalog: stored without one, counted for none"""
        response = rest_api.post(f'{ROUTE_URL}/', json=_manual_payload())

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.CREATED)
        stored = controls.find_one({'public_id': response.get_json()['result_id']})
        assert stored.get(ControlMeasureKey.CATALOG_ID.value) is None
        assert CATALOG_ID not in rest_api.get(STATUS_URL).get_json()

    def test_an_update_keeps_the_stored_catalog_and_ignores_the_bodys(self, rest_api, controls: Any) -> None:
        """The form sends no catalog_id, a client another one: the stored catalog stays"""
        rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One')]))
        stored = _stored(controls)['A.1']
        body = {key: value for key, value in stored.items() if key != 'public_id'}
        body[ControlMeasureKey.CATALOG_ID.value] = OTHER_CATALOG_ID
        body[ControlMeasureKey.REASON.value] = ANSWERED_REASON

        response = rest_api.put(f"{ROUTE_URL}/{stored['public_id']}", json=body)

        assert response.status_code in (HTTPStatus.OK, HTTPStatus.ACCEPTED)
        after = _stored(controls)['A.1']
        assert (after[ControlMeasureKey.CATALOG_ID.value], after[ControlMeasureKey.REASON.value]) == (
            CATALOG_ID, ANSWERED_REASON)


class TestStatusAndDelete:
    """GET .../catalog_status and DELETE .../catalog/<id>"""

    def test_the_status_counts_per_catalog(self, rest_api) -> None:
        """One entry per catalog holding controls"""
        rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One'), _control('A.2', 'Two')]))
        rest_api.post(IMPORT_URL, json=_body([_control('B.1', 'One')], catalog_id=OTHER_CATALOG_ID))

        counts = rest_api.get(STATUS_URL).get_json()

        assert (counts[CATALOG_ID], counts[OTHER_CATALOG_ID]) == (2, 1)

    def test_the_delete_keeps_an_assigned_control(self, rest_api, controls: Any) -> None:
        """The unassigned controls go, the assigned one is kept and reported; the other catalog is untouched"""
        rest_api.post(IMPORT_URL, json=_body([_control('A.1', 'One'), _control('A.2', 'Two')]))
        rest_api.post(IMPORT_URL, json=_body([_control('B.1', 'One')], catalog_id=OTHER_CATALOG_ID))
        stored = _stored(controls)
        controls.database[IsmsControlMeasureAssignment.COLLECTION].insert_one({
            'public_id': ASSIGNMENT_ID, 'control_measure_id': stored['A.2']['public_id'],
        })

        response = rest_api.delete(f'{ROUTE_URL}/catalog/{CATALOG_ID}')

        assert response.status_code == HTTPStatus.OK
        assert response.get_json() == {'successfully': [stored['A.1']['public_id']],
                                       'in_use': [stored['A.2']['public_id']]}
        assert sorted(_stored(controls)) == ['A.2']
        assert sorted(_stored(controls, OTHER_CATALOG_ID)) == ['B.1']
