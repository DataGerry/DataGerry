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
Unit tests for cmdb.models.category_model.cmdb_category

Pure: no Mongo, no Flask. CmdbCategory is the node of the tree the framework UI navigates types by, so
what is pinned here is the document contract (`from_data` / `to_json`, guarded by a round-trip test)
and the small accessors the tree builder reads it through.

Two behaviours are asserted because they were wrong before 2026-08-26: a document missing `public_id`
or `name` fails at construction rather than producing a category whose name is None (which only broke
later, inside `get_label`), and `get_meta` returns the instance's own CategoryMeta rather than a
throw-away default minted per call.
"""
from typing import Any

import pytest

from cmdb.models.category_model.category_constants import CategoryKey, CategoryMetaKey
from cmdb.models.category_model.category_meta import CategoryMeta
from cmdb.models.category_model.cmdb_category import CmdbCategory
from cmdb.models.object_model import CmdbObjectKey
from cmdb.errors.models.cmdb_category import (
    CmdbCategoryInitError,
    CmdbCategoryInitFromDataError,
    CmdbCategoryToJsonError,
)
# -------------------------------------------------------------------------------------------------------------------- #

PUBLIC_ID: int = 3
CATEGORY_NAME: str = 'network-devices'


def _document(**overrides: Any) -> dict[str, Any]:
    """Builds a stored CmdbCategory document with the keys from_data requires."""
    document: dict[str, Any] = {
        CmdbObjectKey.PUBLIC_ID.value: PUBLIC_ID,
        CategoryKey.NAME.value: CATEGORY_NAME,
    }
    document.update(overrides)

    return document


def _category(**overrides: Any) -> CmdbCategory:
    """Builds a CmdbCategory through from_data, which is how the manager builds one."""
    return CmdbCategory.from_data(_document(**overrides))


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      __init__                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
def test_defaults_are_applied() -> None:
    """A category built with only its identity carries the documented defaults"""
    category = _category()

    assert category.public_id == PUBLIC_ID
    assert category.name == CATEGORY_NAME
    assert category.label is None
    assert category.parent is None
    assert category.types == []


def test_types_and_parent_are_kept() -> None:
    """The tree data - membership and the parent link - round-trips onto the attributes"""
    category = _category(**{CategoryKey.PARENT.value: 9, CategoryKey.TYPES.value: [1, 2]})

    assert (category.parent, category.types) == (9, [1, 2])


def test_a_category_may_not_be_its_own_parent() -> None:
    """The backstop for a self-parent that reached the model another way"""
    with pytest.raises(CmdbCategoryInitError):
        CmdbCategory(public_id=PUBLIC_ID, name=CATEGORY_NAME, parent=PUBLIC_ID)


def test_a_root_category_is_not_treated_as_self_parented() -> None:
    """A null parent means 'root'; it must not collide with a null public_id in the guard"""
    assert CmdbCategory(public_id=PUBLIC_ID, name=CATEGORY_NAME, parent=None).parent is None


def test_a_failing_init_is_wrapped() -> None:
    """Anything raised while building the category surfaces as CmdbCategoryInitError"""
    with pytest.raises(CmdbCategoryInitError):
        CmdbCategory(public_id='not-an-id', name=CATEGORY_NAME)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                from_data / to_json                                                   #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('missing', [CmdbObjectKey.PUBLIC_ID, CategoryKey.NAME])
def test_a_missing_required_key_fails_at_construction(missing: Any) -> None:
    """
    Regression: a document without `name` used to build a category with name=None

    That object only broke the next time something asked for its label, with a message naming neither
    the category nor the field. Both keys are required by the schema and `name` is the collection's
    unique index, so a document missing either is refused here.
    """
    document = _document()
    del document[missing.value]

    with pytest.raises(CmdbCategoryInitFromDataError) as exc_info:
        CmdbCategory.from_data(document)

    assert missing.value in str(exc_info.value)


def test_from_data_builds_the_meta_sub_document() -> None:
    """A populated meta sub-document becomes a real CategoryMeta"""
    category = _category(**{CategoryKey.META.value: {
        CategoryMetaKey.ICON.value: 'fa-cube',
        CategoryMetaKey.ORDER.value: 2,
    }})

    assert category.get_meta().get_icon() == 'fa-cube'
    assert category.get_meta().get_order() == 2


@pytest.mark.parametrize('raw_meta', [None, {}, 'not-a-mapping', 0])
def test_an_absent_or_unusable_meta_yields_the_empty_default(raw_meta: Any) -> None:
    """Anything other than a populated mapping means 'no metadata', never a raw value on the attribute"""
    category = _category(**{CategoryKey.META.value: raw_meta})

    assert isinstance(category.get_meta(), CategoryMeta)
    assert category.get_meta().get_icon() == ''
    assert category.get_meta().get_order() is None


def test_to_json_emits_string_keys() -> None:
    """The stored document must be keyed by strings, not by enum members"""
    document = CmdbCategory.to_json(_category())

    assert {type(key).__name__ for key in document} == {'str'}
    assert set(document) == {
        CmdbObjectKey.PUBLIC_ID.value,
        CategoryKey.NAME.value,
        CategoryKey.LABEL.value,
        CategoryKey.META.value,
        CategoryKey.PARENT.value,
        CategoryKey.TYPES.value,
    }


def test_to_json_writes_the_resolved_label() -> None:
    """The serialised document carries the label a client should display, not a null"""
    assert CmdbCategory.to_json(_category())[CategoryKey.LABEL.value] == CATEGORY_NAME.title()


def test_to_json_wraps_a_failure() -> None:
    """A wrong argument is reported as CmdbCategoryToJsonError, not an AttributeError"""
    with pytest.raises(CmdbCategoryToJsonError):
        CmdbCategory.to_json({'public_id': PUBLIC_ID})


def test_from_data_and_to_json_round_trip() -> None:
    """
    The two halves agree on every key name

    A drift between what from_data reads and what to_json writes would be a silently dropped field
    rather than an error - the label is the one deliberate asymmetry, since to_json resolves it.
    """
    original = _category(**{
        CategoryKey.LABEL.value: 'Network Devices',
        CategoryKey.PARENT.value: 9,
        CategoryKey.TYPES.value: [1, 2],
        CategoryKey.META.value: {CategoryMetaKey.ICON.value: 'fa-cube', CategoryMetaKey.ORDER.value: 2},
    })

    assert CmdbCategory.to_json(CmdbCategory.from_data(CmdbCategory.to_json(original))) \
        == CmdbCategory.to_json(original)


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  helper methods                                                      #
# -------------------------------------------------------------------------------------------------------------------- #
def test_get_name_returns_the_unique_name() -> None:
    """The name is the category's identifier, backed by the collection's unique index"""
    assert _category().get_name() == CATEGORY_NAME


def test_get_label_returns_the_set_label() -> None:
    """A configured label wins over the derived one"""
    assert _category(**{CategoryKey.LABEL.value: 'Network Devices'}).get_label() == 'Network Devices'


@pytest.mark.parametrize('label', [None, ''])
def test_get_label_falls_back_to_the_title_cased_name(label: Any) -> None:
    """An unset or empty label displays the title-cased name"""
    assert _category(**{CategoryKey.LABEL.value: label}).get_label() == CATEGORY_NAME.title()


def test_get_label_does_not_write_the_fallback_back() -> None:
    """A reader must not change the CmdbCategory it is reading"""
    category = _category()

    category.get_label()

    assert category.label is None


def test_get_meta_returns_the_instances_own_metadata() -> None:
    """
    Regression: the default used to be a new CategoryMeta per call

    A caller that mutated the result was mutating a throw-away object and silently lost the change.
    """
    category = _category()

    assert category.get_meta() is category.get_meta()

    category.get_meta().icon = 'fa-cube'

    assert category.get_meta().get_icon() == 'fa-cube'
