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
Unit tests for the CmdbSectionTemplate write guards

Pure: no Mongo, no Flask app. These helpers **are** the validation of the write routes -
``CmdbSectionTemplate.SCHEMA`` describes the document rather than the request, and nothing below the
route consults it either: the manager builds the model and inserts its ``__dict__``. So what is
pinned here is what is true of a stored template.

Two of the rules exist because of what happens *after* the write: a template's fields are inlined
into every consuming CmdbType, and its name is the propagation key those types reference it by - and
immutable once stored.
"""
from typing import Any

import pytest
from werkzeug.exceptions import HTTPException

from cmdb.models.section_template_model.section_template_constants import (
    SECTION_TEMPLATE_TEXT_MAX_LENGTH,
    SECTION_TEMPLATE_WRITE_KEYS,
    SectionTemplateKey,
)
from cmdb.models.type_model.field_key_enum import FieldKey
from cmdb.models.type_model.field_type_enum import FieldType
from cmdb.interface.rest_api.routes.framework_routes.cmdb_section_templates.section_template_helper import (
    guard_template_fields,
    require_text,
    strip_unknown_template_keys,
)
# -------------------------------------------------------------------------------------------------------------------- #

HTTP_BAD_REQUEST: int = 400


def _field(**overrides: Any) -> dict[str, Any]:
    """A usable field entry: the three keys a CmdbType field needs."""
    field: dict[str, Any] = {
        FieldKey.NAME.value: 'text-a',
        FieldKey.LABEL.value: 'Text A',
        FieldKey.TYPE.value: FieldType.TEXT.value,
    }
    field.update(overrides)

    return field


# -------------------------------------------------------------------------------------------------------------------- #
#                                             strip_unknown_template_keys                                              #
# -------------------------------------------------------------------------------------------------------------------- #
def test_the_write_keys_are_kept() -> None:
    """Every key a client may set survives untouched"""
    params = {key.value: 'value' for key in SECTION_TEMPLATE_WRITE_KEYS}

    assert strip_unknown_template_keys(params) == params


def test_an_unknown_key_is_dropped() -> None:
    """The model takes **kwargs and the manager inserts its __dict__, so it would be STORED - and
    `to_json` drops it on read, so nothing would ever show it again"""
    stripped = strip_unknown_template_keys({SectionTemplateKey.NAME.value: 'a', 'injected': 'value'})

    assert stripped == {SectionTemplateKey.NAME.value: 'a'}


def test_the_request_parameters_are_not_mutated() -> None:
    """The dict belongs to the request; the normalised payload is the return value"""
    params = {SectionTemplateKey.NAME.value: 'a', 'injected': 'value'}

    strip_unknown_template_keys(params)

    assert 'injected' in params


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    require_text                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_usable_text_is_returned_unchanged() -> None:
    """Surrounding whitespace is tolerated - only a blank value is refused"""
    assert require_text(' My Template ', 'name') == ' My Template '


@pytest.mark.parametrize('raw', ['', '   ', None, 7, [], {}], ids=repr)
def test_blank_text_maps_to_400(raw: Any) -> None:
    """A blank name can never be repaired: it is the propagation key, and immutable once stored"""
    with pytest.raises(HTTPException) as raised:
        require_text(raw, 'name')

    assert raised.value.code == HTTP_BAD_REQUEST
    assert 'name' in raised.value.description


def test_text_at_the_cap_is_accepted() -> None:
    """The boundary belongs to the caller"""
    assert require_text('x' * SECTION_TEMPLATE_TEXT_MAX_LENGTH, 'label')


def test_text_over_the_cap_maps_to_400() -> None:
    """Both values are rendered - the label heads a section, the name identifies the template"""
    with pytest.raises(HTTPException) as raised:
        require_text('x' * (SECTION_TEMPLATE_TEXT_MAX_LENGTH + 1), 'label')

    assert raised.value.code == HTTP_BAD_REQUEST


# -------------------------------------------------------------------------------------------------------------------- #
#                                                guard_template_fields                                                 #
# -------------------------------------------------------------------------------------------------------------------- #
def test_usable_fields_pass() -> None:
    """The ordinary case, and an empty list - a template under construction has no fields yet"""
    guard_template_fields([_field(), _field(**{FieldKey.NAME.value: 'text-b'})])
    guard_template_fields([])


@pytest.mark.parametrize('name', ['', '   ', None, 7], ids=repr)
def test_a_field_without_a_name_maps_to_400(name: Any) -> None:
    """The name is the field's identifier, and an Object keys its stored value by it"""
    with pytest.raises(HTTPException) as raised:
        guard_template_fields([_field(**{FieldKey.NAME.value: name})])

    assert raised.value.code == HTTP_BAD_REQUEST


@pytest.mark.parametrize('label', ['', '  ', None, 7], ids=repr)
def test_a_field_without_a_label_maps_to_400(label: Any) -> None:
    """The label is what the field is rendered as on every form and table of every consuming type"""
    with pytest.raises(HTTPException) as raised:
        guard_template_fields([_field(**{FieldKey.LABEL.value: label})])

    assert raised.value.code == HTTP_BAD_REQUEST


@pytest.mark.parametrize('field_type', ['nonsense', '', None, 7], ids=repr)
def test_an_unknown_field_type_maps_to_400(field_type: Any) -> None:
    """The kind decides how the field is rendered and stored - the same rule the type import applies"""
    with pytest.raises(HTTPException) as raised:
        guard_template_fields([_field(**{FieldKey.TYPE.value: field_type})])

    assert raised.value.code == HTTP_BAD_REQUEST


@pytest.mark.parametrize('field_type', [kind.value for kind in FieldType])
def test_every_known_field_type_is_accepted(field_type: str) -> None:
    """The guard may not narrow what a section can hold"""
    guard_template_fields([_field(**{FieldKey.TYPE.value: field_type})])


def test_a_duplicate_field_name_maps_to_400() -> None:
    """The type these are inlined into would be refused for it by the type structure guard"""
    with pytest.raises(HTTPException) as raised:
        guard_template_fields([_field(), _field()])

    assert raised.value.code == HTTP_BAD_REQUEST
    assert 'text-a' in raised.value.description


def test_the_first_broken_field_is_the_one_reported() -> None:
    """A caller fixes one thing at a time, and the message names which field"""
    with pytest.raises(HTTPException) as raised:
        guard_template_fields([_field(), _field(**{FieldKey.NAME.value: 'text-b',
                                                   FieldKey.LABEL.value: ''})])

    assert 'text-b' in raised.value.description
