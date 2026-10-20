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
Unit tests for cmdb.models.type_model.type_external_link

An external link is a customer-configured URL on a CmdbType whose `{}` placeholders are filled per
rendered object. Two properties carry the weight here:

  - **filling returns a value and never touches the template.** The renderer shares ONE cached CmdbType
    across every object of a type in a batch, so an in-place fill left the first object's values in the
    href and served every following object the first one's URL. `test_filling_leaves_the_template_alone`
    is the model-level half of that guard; the renderer half lives in test_cmdb_multi_render.py
  - **a placeholder-less href is a legitimate link**, not a broken one - it simply needs no fields
"""
import pytest

from cmdb.models.type_model.type_external_link import TypeExternalLink
from cmdb.errors.models.cmdb_type import CmdbTypeExternalFillError, CmdbTypeInitFromDataError
# -------------------------------------------------------------------------------------------------------------------- #

LINK_NAME: str = 'ticket'
DYNAMIC_HREF: str = 'https://tickets.test/{}/'
STATIC_HREF: str = 'https://tickets.test/'
ICON: str = 'fa-ticket'
FIELD_NAME: str = 'dg-name'


def _link(**overrides) -> TypeExternalLink:
    """A TypeExternalLink with a placeholder-carrying href unless a test says otherwise."""
    data = {
        'name': LINK_NAME,
        'href': DYNAMIC_HREF,
        'fields': [FIELD_NAME],
    }
    data.update(overrides)

    return TypeExternalLink.from_data(data)


# -------------------------------------------------------------------------------------------------------------------- #
class TestFromData:
    """Building a link out of a stored type document."""

    def test_reads_the_stored_keys(self) -> None:
        """The ordinary case"""
        link = _link(label='Ticket system', icon=ICON)

        assert (link.name, link.href, link.label, link.icon, link.fields) == (
            LINK_NAME, DYNAMIC_HREF, 'Ticket system', ICON, [FIELD_NAME],
        )

    def test_the_label_defaults_to_the_title_cased_name(self) -> None:
        """A link with no label still renders as something readable"""
        assert _link().label == LINK_NAME.title()

    def test_absent_optionals_become_empty(self) -> None:
        """icon and fields are optional on a stored external"""
        link = TypeExternalLink.from_data({'name': LINK_NAME, 'href': STATIC_HREF})

        assert (link.icon, link.fields) == (None, [])

    @pytest.mark.parametrize('missing', ['name', 'href'], ids=str)
    def test_a_document_without_name_or_href_is_refused(self, missing: str) -> None:
        """
        The two keys a link cannot exist without fail as a model error, not a bare KeyError

        A half-written or hand-edited type document reaches this through CmdbType.from_data, so the
        error has to say which model refused it.
        """
        data = {'name': LINK_NAME, 'href': DYNAMIC_HREF}
        data.pop(missing)

        with pytest.raises(CmdbTypeInitFromDataError):
            TypeExternalLink.from_data(data)


class TestToJson:
    """The wire shape the renderer and the type export both hand out."""

    def test_carries_every_key(self) -> None:
        """The frontend reads all five"""
        assert TypeExternalLink.to_json(_link(icon=ICON)) == {
            'name': LINK_NAME,
            'href': DYNAMIC_HREF,
            'label': LINK_NAME.title(),
            'icon': ICON,
            'fields': [FIELD_NAME],
        }


class TestPredicates:
    """The three questions the renderer asks before filling a link."""

    def test_an_icon_is_reported(self) -> None:
        """The ordinary case"""
        assert _link(icon=ICON).has_icon() is True

    def test_no_icon_is_reported(self) -> None:
        """An external without an icon renders as a plain label"""
        assert _link().has_icon() is False

    def test_a_placeholder_href_requires_fields(self) -> None:
        """The link has to be filled per object"""
        assert _link().link_requires_fields() is True

    def test_a_static_href_requires_none(self) -> None:
        """
        A link that is the same for every object is legitimate, and needs no fields at all

        The renderer short-circuits on this: without it, a static link would be refused for having no
        fields assigned.
        """
        assert _link(href=STATIC_HREF).link_requires_fields() is False

    def test_fields_are_reported(self) -> None:
        """Assigned fields"""
        assert _link().has_fields() is True

    def test_no_fields_is_reported(self) -> None:
        """The state the renderer turns into 'No fields assigned to ExternalLink'"""
        assert _link(fields=[]).has_fields() is False


class TestFilling:
    """Substituting object values into the href."""

    def test_returns_the_filled_href(self) -> None:
        """The ordinary case"""
        assert _link().filled_href(['4711']) == 'https://tickets.test/4711/'

    def test_filling_leaves_the_template_alone(self) -> None:
        """
        The bug this method was reshaped for

        The link belongs to a CmdbType the renderer caches and reuses for every object of that type, so
        writing the filled value back onto the instance served object two the URL of object one.
        """
        link = _link()

        link.filled_href(['first'])

        assert link.href == DYNAMIC_HREF
        assert link.filled_href(['second']) == 'https://tickets.test/second/'

    def test_a_static_href_is_returned_unchanged(self) -> None:
        """Nothing to substitute, and no error for having nothing to substitute"""
        assert _link(href=STATIC_HREF).filled_href([]) == STATIC_HREF

    def test_too_few_values_is_a_fill_error(self) -> None:
        """
        A misconfigured link - more placeholders than assigned fields - names itself in the error

        `format` raises IndexError here, which would mean nothing to a caller looking at a type
        definition; the model's own error carries the href that does not fit.
        """
        with pytest.raises(CmdbTypeExternalFillError) as raised:
            _link().filled_href([])

        assert DYNAMIC_HREF in str(raised.value)

    def test_a_named_placeholder_without_a_value_is_a_fill_error(self) -> None:
        """`{ticket}` is a valid placeholder to the regex but not one positional values can fill"""
        with pytest.raises(CmdbTypeExternalFillError):
            _link(href='https://tickets.test/{ticket}/').filled_href(['4711'])
