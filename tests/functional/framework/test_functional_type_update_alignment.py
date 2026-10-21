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
What `PUT /types/<id>` leaves behind - when it succeeds, and when a step after the write fails

The Type is written once, with `alignment_pending` set; the SpecialType wiring, its Locations, the MDS rows and flat
fields of its Objects and its Reports are then brought in line, and the marker is cleared. Each step is made to fail
in turn: the answer is a 500 naming the step, the Type is saved and still marked, and saving it again - the same
payload, or any other edit - finishes the work. The route's ordinary behaviour is checked too: the full alignment on a
successful save, the marker a client cannot set, and a global template dropped in the one write
"""
from http import HTTPStatus
from typing import Any, Callable

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types import types_helper
from cmdb.interface.rest_api.routes.framework_routes.cmdb_types.types_constants import (
    TYPE_ALIGNMENT_FAILED_MESSAGE,
    TypeAlignmentStep,
)
from cmdb.models.type_model import TypeSchemaKey
from tests.utils import type_alignment_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

ROUTE_URL: str = f'/types/{seed.TYPE_ID}'
CREATE_URL: str = '/types/'
PENDING: str = TypeSchemaKey.ALIGNMENT_PENDING.value

# Every alignment step, the helper it runs (patched to fail once), and how to tell it has run
STEPS: list[Any] = [
    pytest.param(TypeAlignmentStep.LOCATIONS, 'apply_type_changes_to_locations', id='locations'),
    pytest.param(TypeAlignmentStep.MULTI_DATA_SECTIONS, 'apply_type_changes_to_mds', id='mds'),
    pytest.param(TypeAlignmentStep.OBJECT_FIELDS, 'realign_type_object_fields', id='object-fields'),
    pytest.param(TypeAlignmentStep.REPORTS, 'clean_type_reports_after_update', id='reports'),
]


@pytest.fixture(autouse=True)
def _seeded(database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the type and everything that follows it for each test, and removes it after."""
    seed.seed(database_manager, database_name)
    yield
    seed.purge(database_manager, database_name)


@pytest.fixture(name='fail_once')
def fixture_fail_once(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """Makes a types_helper function raise on its first call and run normally after"""
    def _patch(name: str) -> None:
        original = getattr(types_helper, name)
        calls: list[int] = []

        def _failing(*args: Any, **kwargs: Any) -> Any:
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError(f'{name} failed')
            return original(*args, **kwargs)

        monkeypatch.setattr(types_helper, name, _failing)

    return _patch


def _read(rest_api) -> dict[str, Any]:
    """The Type as GET /types/<id> answers it - what the frontend edits"""
    return rest_api.get(ROUTE_URL).get_json()['result']


def _save(rest_api, database_manager: MongoDatabaseManager, database_name: str, **kwargs: Any):
    """PUTs the seeded edit - built from the Type as read, as the frontend does"""
    del database_manager, database_name

    return rest_api.put(ROUTE_URL, json=seed.updated_payload(_read(rest_api), **kwargs))


def _assert_fully_aligned(database_manager: MongoDatabaseManager, database_name: str) -> None:
    """Locations, MDS rows, flat fields and the report in line with the (removing) edit, and the marker cleared"""
    assert seed.node_labels(database_manager, database_name) == {seed.AFTER_LABEL}
    for names in seed.mds_row_names(database_manager, database_name):
        assert names == {seed.MDS_A}
    for names in seed.object_field_names(database_manager, database_name):
        assert seed.DROP not in names and seed.MDS_DROP not in names and seed.KEEP in names
    report = seed.report(database_manager, database_name)
    assert report['selected_fields'] == [seed.KEEP]
    assert report['conditions'] is None
    assert seed.stored_type(database_manager, database_name)[PENDING] is False


class TestASuccessfulSave:
    """The route as it is meant to work."""

    def test_everything_follows_the_type(self, rest_api, database_manager, database_name) -> None:
        """202; the Locations, the Objects (flat fields and MDS rows) and the Report in line; no marker left"""
        response = _save(rest_api, database_manager, database_name)

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        _assert_fully_aligned(database_manager, database_name)

    def test_the_response_and_a_read_show_no_marker(self, rest_api, database_manager, database_name) -> None:
        """The answer is the stored Type, alignment_pending false"""
        response = _save(rest_api, database_manager, database_name)

        assert response.get_json()['result'][PENDING] is False
        assert rest_api.get(ROUTE_URL).get_json()['result'][PENDING] is False

    def test_an_added_field_reaches_every_object_and_row(self, rest_api, database_manager, database_name) -> None:
        """The adding edit: the new flat field and the new MDS field everywhere"""
        response = _save(rest_api, database_manager, database_name, adding=True)

        assert response.status_code == HTTPStatus.ACCEPTED, response.get_json()
        for names in seed.mds_row_names(database_manager, database_name):
            assert names == {seed.MDS_A, seed.MDS_DROP, seed.MDS_NEW}
        for names in seed.object_field_names(database_manager, database_name):
            assert seed.NEW_FIELD in names and seed.MDS_NEW in names

    def test_stored_values_survive(self, rest_api, database_manager, database_name) -> None:
        """The kept field keeps its value; the new field starts empty"""
        _save(rest_api, database_manager, database_name, adding=True)
        stored = database_manager.get_collection('framework.objects', database_name).find_one(
            {'public_id': seed.OBJECT_IDS[0]})
        values = {field['name']: field['value'] for field in stored['fields']}

        assert values[seed.KEEP] == seed.STORED_VALUE
        assert values[seed.NEW_FIELD] is None

    def test_a_client_cannot_set_the_marker(self, rest_api, database_manager, database_name) -> None:
        """alignment_pending in the body is ignored - the server owns it"""
        payload = seed.updated_payload(_read(rest_api))
        payload[PENDING] = True

        assert rest_api.put(ROUTE_URL, json=payload).status_code == HTTPStatus.ACCEPTED
        assert seed.stored_type(database_manager, database_name)[PENDING] is False

    def test_a_created_type_carries_no_marker(self, rest_api, database_manager, database_name) -> None:
        """Nor can a create set it"""
        payload = _read(rest_api)
        payload.update({'name': 'align-created', PENDING: True})
        collection = database_manager.get_collection('framework.types', database_name)

        try:
            response = rest_api.post(CREATE_URL, json=payload)

            assert response.status_code == HTTPStatus.CREATED, response.get_json()
            created_id = response.get_json()['result_id']
            assert collection.find_one({'public_id': created_id}).get(PENDING, False) is False
        finally:
            collection.delete_many({'name': 'align-created'})

    def test_a_dropped_global_template_leaves_in_the_one_write(self, rest_api, database_manager,
                                                               database_name) -> None:
        """Its claim, section and field leave the Type, and the Objects lose the field's values"""
        response = _save(rest_api, database_manager, database_name, drop_template=True)

        assert response.status_code == HTTPStatus.ACCEPTED
        stored = seed.stored_type(database_manager, database_name)
        assert stored['global_template_ids'] == []
        assert seed.TEMPLATE not in {section['name'] for section in stored['render_meta']['sections']}
        assert seed.TEMPLATE_FIELD not in {field['name'] for field in stored['fields']}
        for names in seed.object_field_names(database_manager, database_name):
            assert seed.TEMPLATE_FIELD not in names


class TestAStepThatFails:
    """The Type is saved and marked; the 500 names the step; the next save finishes the work."""

    @pytest.mark.parametrize('step, helper', STEPS)
    def test_the_answer_names_the_step(self, rest_api, database_manager, database_name, fail_once,
                                       step: TypeAlignmentStep, helper: str) -> None:
        """500, and the message says the Type was saved and what to do"""
        fail_once(helper)

        response = _save(rest_api, database_manager, database_name)

        assert response.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert response.get_json()['message'] == TYPE_ALIGNMENT_FAILED_MESSAGE.format(
            public_id=seed.TYPE_ID, step=step.value,
        )

    @pytest.mark.parametrize('step, helper', STEPS)
    def test_the_type_is_saved_and_marked(self, rest_api, database_manager, database_name, fail_once,
                                          step: TypeAlignmentStep, helper: str) -> None:
        """The edit is stored, and a read of the Type shows it is not finished"""
        del step
        fail_once(helper)

        _save(rest_api, database_manager, database_name)

        assert seed.stored_type(database_manager, database_name)['label'] == seed.AFTER_LABEL
        assert rest_api.get(ROUTE_URL).get_json()['result'][PENDING] is True

    @pytest.mark.parametrize('step, helper', STEPS)
    def test_saving_the_same_payload_again_finishes_it(self, rest_api, database_manager, database_name,
                                                       fail_once, step: TypeAlignmentStep, helper: str) -> None:
        """The retry sees no difference to the stored Type - and still brings everything in line"""
        del step
        fail_once(helper)
        payload = seed.updated_payload(_read(rest_api))
        rest_api.put(ROUTE_URL, json=payload)

        retry = rest_api.put(ROUTE_URL, json=payload)

        assert retry.status_code == HTTPStatus.ACCEPTED
        _assert_fully_aligned(database_manager, database_name)

    def test_a_failed_adding_edit_is_finished_too(self, rest_api, database_manager, database_name,
                                                  fail_once) -> None:
        """Added fields: the retry adds them to every object and row"""
        fail_once('apply_type_changes_to_mds')
        payload = seed.updated_payload(_read(rest_api), adding=True)
        rest_api.put(ROUTE_URL, json=payload)

        assert rest_api.put(ROUTE_URL, json=payload).status_code == HTTPStatus.ACCEPTED
        for names in seed.mds_row_names(database_manager, database_name):
            assert seed.MDS_NEW in names
        for names in seed.object_field_names(database_manager, database_name):
            assert seed.NEW_FIELD in names
        assert seed.stored_type(database_manager, database_name)[PENDING] is False

    def test_any_later_edit_finishes_it_too(self, rest_api, database_manager, database_name, fail_once) -> None:
        """Not only the same payload: a save that only renames the Type again"""
        fail_once('realign_type_object_fields')
        _save(rest_api, database_manager, database_name)
        later_edit = _read(rest_api)
        later_edit['description'] = 'only the description changes'

        assert rest_api.put(ROUTE_URL, json=later_edit).status_code == HTTPStatus.ACCEPTED
        _assert_fully_aligned(database_manager, database_name)

    def test_the_steps_before_the_failure_are_done(self, rest_api, database_manager, database_name,
                                                   fail_once) -> None:
        """The flat-field step failed: the Locations and the MDS rows were already brought in line, the fields not"""
        fail_once('realign_type_object_fields')

        _save(rest_api, database_manager, database_name)

        assert seed.node_labels(database_manager, database_name) == {seed.AFTER_LABEL}
        for names in seed.mds_row_names(database_manager, database_name):
            assert names == {seed.MDS_A}
        for names in seed.object_field_names(database_manager, database_name):
            assert seed.DROP in names
