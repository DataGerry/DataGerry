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
Unit tests for cmdb.framework.section_templates.virtual_section_templates

Three things about a virtual template are contracts rather than implementation details, and each has
its own test here:

* it is DERIVED from the port model's field constants, so the template and the collection cannot
  drift - the test that matters most is the one that fails when a port field is added without a
  presentation spec
* it carries NO public_id, which would make it look like a stored resource - but it IS flagged
  ``predefined``, which is what tells the frontend the section is system-owned and must stay locked
* its selects carry `option_type` instead of an inline `options` list, because their values are
  CmdbExtendableOptions

Pure tests: no Mongo, no Flask
"""
from typing import Any

import pytest

from cmdb.models.extendable_option_model import OptionType
from cmdb.models.port_model import (
    PORT_SELECT_FIELD_OPTION_TYPES,
    PORT_TEMPLATE_FIELD_KEYS,
    PortKey,
)
from cmdb.models.section_template_model.section_template_constants import SectionTemplateKey
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.models.type_model.section_type_enum import SectionType
from cmdb.framework.section_templates.virtual_section_templates import (
    PORT_FIELD_PRESENTATION,
    PORTS_VIRTUAL_TEMPLATE_NAME,
    REQUIRED_PORT_FIELDS,
    VIRTUAL_TEMPLATE_NAME_PREFIX,
    build_virtual_port_field,
    get_ports_virtual_template,
    get_virtual_section_templates,
    is_virtual_template_name,
)
# -------------------------------------------------------------------------------------------------------------------- #


def _fields() -> list[dict[str, Any]]:
    """The ports virtual template's field list."""
    return get_ports_virtual_template()[SectionTemplateKey.FIELDS.value]


def _field(name: str) -> dict[str, Any]:
    """One field of the ports virtual template, by name."""
    return next(field for field in _fields() if field[FieldKey.NAME.value] == name)


# -------------------------------------------------------------------------------------------------------------------- #
#                                          derived from the port model                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheFieldsAreDerived:
    """The template and the port collection cannot drift."""

    def test_the_fields_are_the_port_template_keys_in_order(self) -> None:
        """
        Content AND order come from PORT_TEMPLATE_FIELD_KEYS

        The order is what the user sees, so it is part of the contract, not an accident of iteration.
        """
        assert [field[FieldKey.NAME.value] for field in _fields()] == \
            [key.value for key in PORT_TEMPLATE_FIELD_KEYS]

    def test_every_port_template_field_has_a_presentation_spec(self) -> None:
        """
        THE drift test: a port field added without a spec must fail loudly, not vanish from the UI

        Deriving the list is only half the protection - without this, a new field would raise at
        request time instead of at test time.
        """
        missing = [key.value for key in PORT_TEMPLATE_FIELD_KEYS if key not in PORT_FIELD_PRESENTATION]

        assert not missing, f"port field(s) without a virtual-template presentation spec: {missing}"

    def test_a_field_without_a_spec_raises(self) -> None:
        """The failure mode is an exception, so it cannot be mistaken for an empty section"""
        with pytest.raises(KeyError):
            build_virtual_port_field(PortKey.OBJECT_ID)

    def test_no_server_owned_field_is_offered(self) -> None:
        """A server-owned field in the form would look editable"""
        server_owned = {
            PortKey.PUBLIC_ID.value, PortKey.OBJECT_ID.value, PortKey.SIDE.value,
            PortKey.AUTHOR_ID.value, PortKey.CREATION_TIME.value, PortKey.LAST_EDIT_TIME.value,
        }

        assert not server_owned & {field[FieldKey.NAME.value] for field in _fields()}

    def test_the_presentation_map_offers_nothing_extra(self) -> None:
        """
        A spec for a field that is not in the template list would be dead configuration

        Guards the map against growing entries the derivation never reads.
        """
        assert set(PORT_FIELD_PRESENTATION) == set(PORT_TEMPLATE_FIELD_KEYS)


# -------------------------------------------------------------------------------------------------------------------- #
#                                         what makes it VIRTUAL                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestItIsVirtual:
    """The keys a virtual template must not have, and the ones it must."""

    def test_it_has_no_public_id(self) -> None:
        """It is not a resource: nothing can be fetched, updated or counted by id"""
        assert SectionTemplateKey.PUBLIC_ID.value not in get_ports_virtual_template()

    def test_it_is_flagged_predefined(self) -> None:
        """
        What tells the frontend the section is system-owned, so the builder keeps it locked

        The flag carries the same meaning it has on the stored routes - a predefined template is
        neither editable nor deletable - which is true of a virtual one twice over. It does NOT drag
        the fields under the predefined-select guard: that guard resolves predefined template names
        out of the collection, which this template is never in.
        """
        assert get_ports_virtual_template()[SectionTemplateKey.PREDEFINED.value] is True

    def test_it_is_a_global_multi_data_section(self) -> None:
        """Global so it appears in the drag-and-drop palette; MDS because a device has many ports"""
        template = get_ports_virtual_template()

        assert template[SectionTemplateKey.IS_GLOBAL.value] is True
        assert template[SectionTemplateKey.TYPE.value] == SectionType.MDS_SECTION.value

    def test_its_name_is_in_the_reserved_space(self) -> None:
        """Which is what stops a stored template from shadowing it"""
        assert PORTS_VIRTUAL_TEMPLATE_NAME.startswith(VIRTUAL_TEMPLATE_NAME_PREFIX)

    def test_the_name_is_pinned(self) -> None:
        """The frontend resolves it by name, so the literal is a contract"""
        assert PORTS_VIRTUAL_TEMPLATE_NAME == 'dg-virtual-tpl-ports'


# -------------------------------------------------------------------------------------------------------------------- #
#                                              the select fields                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheSelectFields:
    """Their values live in framework.extendableOptions, not on the field."""

    @pytest.mark.parametrize('field_key, option_type', sorted(
        PORT_SELECT_FIELD_OPTION_TYPES.items(), key=lambda item: item[0].value,
    ), ids=lambda value: value.value)
    def test_each_select_names_its_option_type(self, field_key: PortKey, option_type: OptionType) -> None:
        """
        Which list a select draws from comes from the port model's own map

        This is what lets the frontend load the values and extend them through
        POST /extendable_options/ without a new route.
        """
        field = _field(field_key.value)

        assert field[FieldKey.TYPE.value] == FieldType.SELECT.value
        assert field[FieldKey.OPTION_TYPE.value] == option_type.value

    def test_a_select_carries_no_inline_options(self) -> None:
        """
        An inline list would be a second, stale copy of a CmdbExtendableOption list

        Every stored template's select has one; this is the first whose values come from a collection.
        """
        for field_key in PORT_SELECT_FIELD_OPTION_TYPES:
            assert FieldKey.OPTIONS.value not in _field(field_key.value)

    def test_every_option_type_is_a_real_one(self) -> None:
        """A typo here would send the frontend looking for a list that does not exist"""
        known = {option_type.value for option_type in OptionType}

        for field_key in PORT_SELECT_FIELD_OPTION_TYPES:
            assert _field(field_key.value)[FieldKey.OPTION_TYPE.value] in known

    def test_only_the_selects_carry_an_option_type(self) -> None:
        """A text field with an option_type would be nonsense the frontend might act on"""
        with_option_type = {
            field[FieldKey.NAME.value] for field in _fields() if FieldKey.OPTION_TYPE.value in field
        }

        assert with_option_type == {key.value for key in PORT_SELECT_FIELD_OPTION_TYPES}


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the rest of the shape                                                     #
# -------------------------------------------------------------------------------------------------------------------- #
class TestFieldShape:
    """Types, labels and the one required field."""

    def test_every_field_has_a_type_a_name_and_a_label(self) -> None:
        """The three keys the frontend needs to render an input at all"""
        for field in _fields():
            assert field[FieldKey.TYPE.value]
            assert field[FieldKey.NAME.value]
            assert field[FieldKey.LABEL.value]

    def test_the_field_types_match_the_document(self) -> None:
        """A number input for the port number, text for the name and description"""
        assert _field(PortKey.NAME.value)[FieldKey.TYPE.value] == FieldType.TEXT.value
        assert _field(PortKey.PORT_NUMBER.value)[FieldKey.TYPE.value] == FieldType.NUMBER.value
        assert _field(PortKey.DESCRIPTION.value)[FieldKey.TYPE.value] == FieldType.TEXT.value

    def test_the_name_is_the_only_required_field(self) -> None:
        """
        Matching the create route, which refuses a blank name and nothing else

        A form requiring more than the route does would block a request the backend accepts.
        """
        required = {field[FieldKey.NAME.value] for field in _fields() if field.get(FieldKey.REQUIRED.value)}

        assert required == {key.value for key in REQUIRED_PORT_FIELDS}
        assert required == {PortKey.NAME.value}

    def test_every_field_type_is_a_real_one(self) -> None:
        """A typo would render as nothing"""
        known = {field_type.value for field_type in FieldType}

        for field in _fields():
            assert field[FieldKey.TYPE.value] in known


# -------------------------------------------------------------------------------------------------------------------- #
#                                       the collection and the prefix check                                            #
# -------------------------------------------------------------------------------------------------------------------- #
class TestTheCollection:
    """What the route serves."""

    def test_the_ports_template_is_offered(self) -> None:
        """One virtual template today; the route returns a list so a second needs no route change"""
        names = [template[SectionTemplateKey.NAME.value] for template in get_virtual_section_templates()]

        assert names == [PORTS_VIRTUAL_TEMPLATE_NAME]

    def test_each_call_builds_a_fresh_definition(self) -> None:
        """
        A shared dict could be mutated by a caller and served mutated to the next one

        The route hands these straight into a response, so they must not be shared state.
        """
        first = get_ports_virtual_template()
        first[SectionTemplateKey.FIELDS.value].clear()

        assert get_ports_virtual_template()[SectionTemplateKey.FIELDS.value]


class TestIsVirtualTemplateName:
    """The reserved-name check the create route uses."""

    @pytest.mark.parametrize('name', [
        'dg-virtual-tpl-ports',
        'dg-virtual-tpl-',
        'dg-virtual-tpl-anything-at-all',
    ], ids=['the-ports-one', 'bare-prefix', 'a-future-one'])
    def test_reserved_names_are_recognised(self, name: str) -> None:
        """The whole prefix is reserved, not just the name in use today"""
        assert is_virtual_template_name(name) is True

    @pytest.mark.parametrize('name', [
        'dg-ipam-interface',
        'ports',
        'my-dg-virtual-tpl-ports',
        '',
    ], ids=['a-predefined-one', 'plain', 'prefix-not-at-the-start', 'empty'])
    def test_ordinary_names_are_not(self, name: str) -> None:
        """The check is a prefix match, so a name merely containing it is fine"""
        assert is_virtual_template_name(name) is False

    @pytest.mark.parametrize('name', [None, 7, ['dg-virtual-tpl-ports']], ids=['none', 'int', 'list'])
    def test_a_non_string_is_not_reserved(self, name: Any) -> None:
        """It runs on a raw request body, so it must not raise on a malformed name"""
        assert is_virtual_template_name(name) is False
