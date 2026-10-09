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
Integration tests for the data a DocAPI template reads from an object's references, against a real MongoDB

Driven through the real `DocApiRenderer` - the path the render route takes - with the template engine's input
captured, so what is checked is exactly the data a template gets: a plain reference and its next hop, a
reference section and `object(<id>)`'s reference resolve; a reference the caller may not read is empty; a location
field is its location's name and never an object, whatever the field is called. For both template types
"""
from typing import Any

import pytest

from cmdb.database import MongoDatabaseManager
from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.manager import ObjectsManager
from cmdb.manager.manager_provider_model import ManagerProvider, ManagerType
from cmdb.models.docapi_model.docapi_renderer import DocApiRenderer
from cmdb.models.docapi_model.reference_result import ReferenceResult
from cmdb.models.docapi_model.template_engine import TemplateEngine
from cmdb.models.object_model import CmdbObject
from cmdb.models.user_model import CmdbUser
from tests.utils import docapi_reference_seed as seed
# -------------------------------------------------------------------------------------------------------------------- #

FIELDS: str = 'fields'
PDF_MAGIC: bytes = b'%PDF'


@pytest.fixture(autouse=True)
def _seeded(rest_api, database_manager: MongoDatabaseManager, database_name: str):
    """Seeds the reference fixture and pushes the request context ManagerProvider resolves through."""
    seed.seed(database_manager, database_name)

    with rest_api.application.test_request_context():
        yield

    seed.purge(database_manager, database_name)


@pytest.fixture(name='template_input')
def fixture_template_input(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Captures the data the template engine is handed."""
    captured: list[dict[str, Any]] = []
    original = TemplateEngine.render_template_string

    def _capturing(template_str: str, data: dict[str, Any]) -> str:
        captured.append(data)
        return original(template_str, data)

    monkeypatch.setattr(TemplateEngine, 'render_template_string', staticmethod(_capturing))

    return captured


def _generate(database_manager: MongoDatabaseManager, database_name: str, template_id: int,
              user: CmdbUser) -> bytes:
    """Renders ROOT with `template_id` for `user`, the way the render route does; answers the document"""
    objects_manager: ObjectsManager = ManagerProvider.get_manager(ManagerType.OBJECTS, user)
    template = DocapiTemplate.from_data(
        database_manager.get_collection(DocapiTemplate.COLLECTION, database_name).find_one({'public_id': template_id}))
    root = CmdbObject.from_data(
        database_manager.get_collection(CmdbObject.COLLECTION, database_name).find_one({'public_id': seed.ROOT_ID}))

    return DocApiRenderer(objects_manager, template, root).render_object_template(user).getvalue()


class TestTheDefaultTemplate:
    """`root.fields...` and `object(<id>)`."""

    def test_the_document_is_generated(self, database_manager, database_name, full_access_user) -> None:
        """The generator still answers a PDF"""
        assert _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, full_access_user) \
            .startswith(PDF_MAGIC)

    def test_a_reference_and_its_next_hop_resolve(self, database_manager, database_name, full_access_user,
                                                  template_input) -> None:
        """MID, wrapped, and inside it LEAF - two hops"""
        _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, full_access_user)
        mid: Any = template_input[-1]['root'][FIELDS][seed.MID_REF]

        assert isinstance(mid, ReferenceResult)
        assert mid.obj_data[FIELDS][seed.NAME_FIELD] == seed.MID_VALUE
        assert mid.obj_data[FIELDS][seed.LEAF_REF].obj_data[FIELDS][seed.NAME_FIELD] == seed.LEAF_VALUE

    def test_a_reference_section_carries_its_values(self, database_manager, database_name, full_access_user,
                                                    template_input) -> None:
        """MID's main section, by name"""
        _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, full_access_user)

        assert template_input[-1]['root'][FIELDS][seed.REF_SECTION_FIELD][FIELDS][seed.NAME_FIELD] == seed.MID_VALUE

    def test_a_location_field_is_its_location(self, database_manager, database_name, full_access_user,
                                              template_input) -> None:
        """Not named dg_location, still the location's name - not the decoy object sharing its id"""
        _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, full_access_user)

        assert template_input[-1]['root'][FIELDS][seed.PLACEMENT_FIELD] == seed.LOCATION_NAME

    def test_a_reference_the_caller_may_not_read_is_empty(self, database_manager, database_name,
                                                          template_input) -> None:
        """The default user group may not read HIDDEN: nothing of it reaches the template"""
        _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, seed.default_user())
        fields: dict[str, Any] = template_input[-1]['root'][FIELDS]

        assert not fields[seed.HIDDEN_REF]
        assert seed.HIDDEN_VALUE not in repr(template_input[-1])
        assert fields[seed.MID_REF].obj_data[FIELDS][seed.NAME_FIELD] == seed.MID_VALUE

    def test_the_admin_reads_the_hidden_reference(self, database_manager, database_name, full_access_user,
                                                  template_input) -> None:
        """The admin group may"""
        _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, full_access_user)

        assert template_input[-1]['root'][FIELDS][seed.HIDDEN_REF].obj_data[FIELDS][seed.NAME_FIELD] \
            == seed.HIDDEN_VALUE

    def test_an_object_the_template_names_carries_its_references(self, database_manager, database_name,
                                                                 full_access_user, template_input) -> None:
        """object(<MID>) reads into its own reference to LEAF"""
        _generate(database_manager, database_name, seed.DEFAULT_TEMPLATE_ID, full_access_user)
        mid: Any = template_input[-1]['object'](seed.MID_ID)

        assert mid[FIELDS][seed.LEAF_REF][FIELDS][seed.NAME_FIELD] == seed.LEAF_VALUE


class TestTheObjectTemplate:
    """The legacy OBJECT template's `fields...`."""

    def test_the_document_is_generated(self, database_manager, database_name, full_access_user) -> None:
        """The generator still answers a PDF"""
        assert _generate(database_manager, database_name, seed.OBJECT_TEMPLATE_ID, full_access_user) \
            .startswith(PDF_MAGIC)

    def test_a_reference_and_its_next_hop_resolve(self, database_manager, database_name, full_access_user,
                                                  template_input) -> None:
        """Plain dicts, two hops"""
        _generate(database_manager, database_name, seed.OBJECT_TEMPLATE_ID, full_access_user)
        mid: dict[str, Any] = template_input[-1][FIELDS][seed.MID_REF]

        assert mid[FIELDS][seed.NAME_FIELD] == seed.MID_VALUE
        assert mid[FIELDS][seed.LEAF_REF][FIELDS][seed.NAME_FIELD] == seed.LEAF_VALUE

    def test_a_location_field_is_its_location(self, database_manager, database_name, full_access_user,
                                              template_input) -> None:
        """The same rule in the legacy shape"""
        _generate(database_manager, database_name, seed.OBJECT_TEMPLATE_ID, full_access_user)

        assert template_input[-1][FIELDS][seed.PLACEMENT_FIELD] == seed.LOCATION_NAME

    def test_a_reference_the_caller_may_not_read_is_empty(self, database_manager, database_name,
                                                          template_input) -> None:
        """None, like an unset reference"""
        _generate(database_manager, database_name, seed.OBJECT_TEMPLATE_ID, seed.default_user())

        assert template_input[-1][FIELDS][seed.HIDDEN_REF] is None
        assert seed.HIDDEN_VALUE not in repr(template_input[-1])
