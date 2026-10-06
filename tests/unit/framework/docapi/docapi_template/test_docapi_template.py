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
Unit tests for cmdb.framework.docapi.docapi_template.docapi_template.DocapiTemplate

Pure tests (no app context, no database). Covers from_data / to_json (round-trip and defaults), the
DocapiTemplateType default, the string/dict getters (present and None branches) and get_public_id's
NoPublicIDError guard.

Also the CmdbDAO contract the model now shares: the shared from_data / to_json driven by DocapiTemplateKey
(name and public_id required, public_id read as an integer, a wrong instance refused), the keyword-only
constructor that drops undeclared keys, `active` defaulting to True, and the two declared indexes.
"""
from types import SimpleNamespace

import pytest

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
from cmdb.models.docapi_model import DocapiTemplateType
from cmdb.models.cmdb_dao import CmdbDAO
from cmdb.errors.cmdb_object import NoPublicIDError, RequiredInitKeyNotFoundError
from cmdb.errors.models.docapi_template import DocapiTemplateInitFromDataError, DocapiTemplateToJsonError
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 5
NAME: str = "invoice"
LABEL: str = "Invoice"
DESCRIPTION: str = "Invoice template"
AUTHOR_ID: int = 3
TEMPLATE_DATA: str = "<h1>{{ name }}</h1>"
TEMPLATE_STYLE: str = "body { color: #000; }"
HEADER: dict = {"activated": True}
PAGE_CONFIG: dict = {"margin": {"margin-top": 10}}


def _template(**overrides) -> DocapiTemplate:
    """Builds a DocapiTemplate from a full data dict, applying any overrides."""
    data = {
        DocapiTemplateKey.PUBLIC_ID: PUBLIC_ID,
        DocapiTemplateKey.NAME: NAME,
        DocapiTemplateKey.LABEL: LABEL,
        DocapiTemplateKey.DESCRIPTION: DESCRIPTION,
        DocapiTemplateKey.ACTIVE: True,
        DocapiTemplateKey.AUTHOR_ID: AUTHOR_ID,
        DocapiTemplateKey.TEMPLATE_DATA: TEMPLATE_DATA,
        DocapiTemplateKey.TEMPLATE_STYLE: TEMPLATE_STYLE,
        DocapiTemplateKey.TEMPLATE_TYPE: DocapiTemplateType.OBJECT,
        DocapiTemplateKey.HEADER: HEADER,
        DocapiTemplateKey.PAGE_CONFIG: PAGE_CONFIG,
    }
    data.update(overrides)
    return DocapiTemplate.from_data(data)


class TestFromData:
    """from_data maps the payload onto the model, defaulting the optional keys."""

    def test_required_and_optional_mapped(self) -> None:
        """Required and provided optional keys are mapped onto the instance."""
        template = _template()

        assert template.get_public_id() == PUBLIC_ID
        assert template.name == NAME
        assert template.header == HEADER

    def test_missing_optionals_default(self) -> None:
        """Omitted component keys default to empty dicts and scalars to None."""
        template = DocapiTemplate.from_data({
            DocapiTemplateKey.PUBLIC_ID: PUBLIC_ID,
            DocapiTemplateKey.NAME: NAME,
        })

        assert template.header == {}
        assert template.footer == {}
        assert template.table_of_contents == {}
        assert template.cover_page == {}
        assert template.page_config == {}
        assert template.label is None

    def test_default_template_type(self) -> None:
        """A missing template_type defaults to OBJECT."""
        template = DocapiTemplate.from_data({
            DocapiTemplateKey.PUBLIC_ID: PUBLIC_ID,
            DocapiTemplateKey.NAME: NAME,
        })

        assert template.template_type == DocapiTemplateType.OBJECT


class TestToJson:
    """to_json emits every serialization key and round-trips through from_data."""

    def test_contains_all_keys(self) -> None:
        """The serialized dict exposes every DocapiTemplateKey."""
        result = DocapiTemplate.to_json(_template())

        assert set(result.keys()) == set(DocapiTemplateKey)

    def test_round_trip(self) -> None:
        """to_json output fed back through from_data preserves the values."""
        restored = DocapiTemplate.from_data(DocapiTemplate.to_json(_template()))

        assert restored.get_public_id() == PUBLIC_ID
        assert restored.name == NAME
        assert restored.page_config == PAGE_CONFIG


class TestGetPublicId:
    """get_public_id returns the id or raises when it is unset."""

    def test_returns_id(self) -> None:
        """A set public_id is returned."""
        assert _template().get_public_id() == PUBLIC_ID

    def test_zero_raises(self) -> None:
        """A public_id of 0 raises NoPublicIDError."""
        with pytest.raises(NoPublicIDError):
            _template(public_id=0).get_public_id()

    def test_none_is_refused_when_read(self) -> None:
        """A document whose public_id is null is no template: it is refused while being read."""
        with pytest.raises(DocapiTemplateInitFromDataError):
            _template(public_id=None)

    def test_a_string_id_is_read_as_an_integer(self) -> None:
        """CmdbDAO converts the id, so a lookup by it finds the stored template."""
        assert _template(public_id=str(PUBLIC_ID)).get_public_id() == PUBLIC_ID


class TestScalarGetters:
    """The string/bool/int getters return the value or their None-safe fallback."""

    def test_present_values(self) -> None:
        """Each getter returns its stored value when set."""
        template = _template()

        assert template.get_name() == NAME
        assert template.get_label() == LABEL
        assert template.get_description() == DESCRIPTION
        assert template.get_active() is True
        assert template.get_author_id() == AUTHOR_ID
        assert template.get_template_data() == TEMPLATE_DATA
        assert template.get_template_style() == TEMPLATE_STYLE

    def test_none_name_label_description_become_empty(self) -> None:
        """name / label / description fall back to an empty string when None."""
        template = _template(name=None, label=None, description=None)

        assert template.get_name() == ""
        assert template.get_label() == ""
        assert template.get_description() == ""

    def test_a_missing_or_null_active_reads_as_true(self) -> None:
        """A document without the flag reads as the constructor's default - it used to read as null."""
        data = {DocapiTemplateKey.PUBLIC_ID: PUBLIC_ID, DocapiTemplateKey.NAME: NAME}

        assert DocapiTemplate.from_data(data).active is True
        assert _template(active=None).get_active() is True

    def test_a_stored_false_stays_false(self) -> None:
        """Only an absent flag is defaulted."""
        assert _template(active=False).get_active() is False

    def test_a_non_true_active_is_false(self) -> None:
        """get_active returns False for any value that is not True."""
        assert _template(active='yes').get_active() is False

    def test_none_author_id_returned_as_none(self) -> None:
        """author_id is returned as-is (None allowed)."""
        assert _template(author_id=None).get_author_id() is None


class TestComponentGetters:
    """The component getters return the stored dicts."""

    def test_component_dicts(self) -> None:
        """Header / footer / toc / cover_page / page_config are returned as stored."""
        template = _template()

        assert template.get_header() == HEADER
        assert template.get_footer() == {}
        assert template.get_table_of_contents() == {}
        assert template.get_cover_page() == {}
        assert template.get_page_config() == PAGE_CONFIG


class TestTheCmdbDaoContract:
    """DocapiTemplate shares CmdbDAO's construction, serialisation and index rules."""

    def test_it_is_a_cmdb_dao(self) -> None:
        """The bespoke base is gone."""
        assert issubclass(DocapiTemplate, CmdbDAO)

    @pytest.mark.parametrize('missing', [DocapiTemplateKey.PUBLIC_ID, DocapiTemplateKey.NAME])
    def test_a_document_missing_a_required_key_is_refused(self, missing: DocapiTemplateKey) -> None:
        """public_id and name: the by-name route resolves a template by nothing else."""
        data = {DocapiTemplateKey.PUBLIC_ID.value: PUBLIC_ID, DocapiTemplateKey.NAME.value: NAME}
        del data[missing.value]

        with pytest.raises(DocapiTemplateInitFromDataError):
            DocapiTemplate.from_data(data)

    def test_a_construction_without_public_id_is_refused(self) -> None:
        """CmdbDAO.__new__ checks the required keys before the constructor runs."""
        with pytest.raises(RequiredInitKeyNotFoundError):
            DocapiTemplate(name=NAME)

    def test_the_constructor_is_keyword_only(self) -> None:
        """A positional call could never have passed __new__'s keyword check."""
        with pytest.raises((TypeError, RequiredInitKeyNotFoundError)):
            DocapiTemplate(PUBLIC_ID, NAME)  # pylint: disable=too-many-function-args

    def test_an_undeclared_key_is_dropped(self) -> None:
        """The routes construct from the raw body: a stray key becomes no attribute and no stored value."""
        template = DocapiTemplate(public_id=PUBLIC_ID, name=NAME, evil=1)

        assert not hasattr(template, 'evil')
        assert 'evil' not in DocapiTemplate.to_json(template)

    def test_to_json_refuses_another_model(self) -> None:
        """A look-alike object is not serialised as a template."""
        look_alike = SimpleNamespace(**DocapiTemplate.to_json(_template()))

        with pytest.raises(DocapiTemplateToJsonError):
            DocapiTemplate.to_json(look_alike)

    def test_to_json_answers_plain_string_keys(self) -> None:
        """The wire keys are the enum's values."""
        keys = list(DocapiTemplate.to_json(_template()))

        assert all(type(key) is str for key in keys)  # pylint: disable=unidiomatic-typecheck

    def test_the_two_indexes_are_declared(self) -> None:
        """The unique name index plus CmdbDAO's unique public_id index."""
        indexes = {index.document['name']: index.document for index in DocapiTemplate.get_index_keys()}

        assert set(indexes) == {'name', 'public_id'}
        assert all(index['unique'] for index in indexes.values())
