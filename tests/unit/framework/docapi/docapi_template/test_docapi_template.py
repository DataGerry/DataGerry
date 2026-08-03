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
"""
import pytest

from cmdb.framework.docapi.docapi_template.docapi_template import DocapiTemplate
from cmdb.framework.docapi.docapi_template.docapi_template_constants import DocapiTemplateKey
from cmdb.models.docapi_model import DocapiTemplateType
from cmdb.errors.cmdb_object import NoPublicIDError
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

        assert template.footer == {}
        assert template.cover_page == {}
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

    def test_none_raises(self) -> None:
        """A None public_id raises NoPublicIDError."""
        with pytest.raises(NoPublicIDError):
            _template(public_id=None).get_public_id()


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

    def test_non_true_active_is_false(self) -> None:
        """get_active returns False for any non-True value."""
        assert _template(active=None).get_active() is False

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
