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
Unit tests for cmdb.framework.port.name_preview

What the customer is shown before 48 ports exist. Two things carry these tests:

* **a patch panel's two faces are checked for collisions separately.** A port name is unique within a
  face, so a panel's existing front 1 must not be reported as a clash for its new rear 1 - the mistake
  that would make every panel look unbuildable
* **one count drives both faces.** The concept's "equal numbers, every element paired" rule is made
  unbreakable by there being no way to ask for 24 front and 18 rear, so no validator ever has to refuse
  that combination

Pure tests: the existing names are handed in as sets
"""
import pytest

from cmdb.framework.port.name_preview import (
    build_face,
    build_panel_preview,
    build_standard_preview,
    preview_has_collisions,
)
from cmdb.framework.port.name_syntax_constants import PortCollisionKey, PortPreviewKey
from cmdb.models.port_model import PortSide
# -------------------------------------------------------------------------------------------------------------------- #


def _faces(preview: dict) -> list[dict]:
    """The face entries of a preview."""
    return preview[PortPreviewKey.FACES.value]


def _names(face: dict) -> list[str]:
    """The generated names of one face."""
    return face[PortPreviewKey.NAMES.value]


def _existing(face: dict) -> list[str]:
    """The existing-name collisions of one face."""
    return face[PortPreviewKey.COLLISIONS.value][PortCollisionKey.EXISTING.value]


def _duplicates(face: dict) -> list[str]:
    """The within-batch duplicates of one face."""
    return face[PortPreviewKey.COLLISIONS.value][PortCollisionKey.DUPLICATES.value]


# -------------------------------------------------------------------------------------------------------------------- #
#                                                      one face                                                        #
# -------------------------------------------------------------------------------------------------------------------- #
class TestBuildFace:
    """The unit both device kinds are made of."""

    def test_a_face_carries_its_side_and_its_names(self) -> None:
        """The side is what the created ports will be stored with"""
        face = build_face(PortSide.FRONT.value, '{n}', 2, set())

        assert face[PortPreviewKey.SIDE.value] == PortSide.FRONT.value
        assert _names(face) == ['1', '2']

    def test_both_kinds_of_collision_are_reported_together(self) -> None:
        """
        A customer fixing a syntax wants to see all of it at once

        The two are reported apart because the fix differs: a duplicate needs {n} added, a clash needs
        a different prefix or a higher start index.
        """
        face = build_face(PortSide.SINGLE.value, 'fixed', 2, {'fixed'})

        assert _duplicates(face) == ['fixed']
        assert _existing(face) == ['fixed']

    def test_a_clean_face_reports_no_collisions(self) -> None:
        """The ordinary case"""
        face = build_face(PortSide.SINGLE.value, 'Gi0/{n}', 3, {'Te1/1'})

        assert _duplicates(face) == []
        assert _existing(face) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                 a standard device                                                    #
# -------------------------------------------------------------------------------------------------------------------- #
class TestStandardPreview:
    """n plain ports, one face, no pairing."""

    def test_it_has_exactly_one_face_of_single_ports(self) -> None:
        """A standard device has no sides - the kind is what decides that, not the user"""
        preview = build_standard_preview('Gi0/{n}', 3, set())

        assert len(_faces(preview)) == 1
        assert _faces(preview)[0][PortPreviewKey.SIDE.value] == PortSide.SINGLE.value

    def test_the_total_is_the_port_count(self) -> None:
        """One face, so the total is its length"""
        assert build_standard_preview('Gi0/{n}', 24, set())[PortPreviewKey.TOTAL.value] == 24

    def test_it_carries_no_pairing(self) -> None:
        """Only a panel has pairs; a standard device's ports connect to nothing internally"""
        assert PortPreviewKey.PAIRS.value not in build_standard_preview('{n}', 2, set())

    def test_existing_names_are_reported(self) -> None:
        """Adding a second batch to a switch that already has ports"""
        preview = build_standard_preview('Gi0/{n}', 3, {'Gi0/2'})

        assert _existing(_faces(preview)[0]) == ['Gi0/2']

    def test_the_start_index_moves_the_batch_past_the_existing_ports(self) -> None:
        """The documented way out of a collision"""
        preview = build_standard_preview('Gi0/{n}', 2, {'Gi0/1', 'Gi0/2'}, start_index=3)

        assert _names(_faces(preview)[0]) == ['Gi0/3', 'Gi0/4']
        assert _existing(_faces(preview)[0]) == []


# -------------------------------------------------------------------------------------------------------------------- #
#                                                  a patch panel                                                       #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPanelPreview:
    """Two faces, named independently, paired positionally."""

    def test_it_has_a_front_and_a_rear_face(self) -> None:
        """The concept's two syntaxes, because the faces are labelled differently far more often"""
        preview = build_panel_preview('F{n}', 'R{n}', 2, set(), set())

        assert [face[PortPreviewKey.SIDE.value] for face in _faces(preview)] == [
            PortSide.FRONT.value, PortSide.REAR.value,
        ]
        assert _names(_faces(preview)[0]) == ['F1', 'F2']
        assert _names(_faces(preview)[1]) == ['R1', 'R2']

    def test_one_count_drives_both_faces(self) -> None:
        """
        How 'equal numbers, every element paired' is made unbreakable

        There is no way to ask for 24 front and 18 rear, so no validator ever has to refuse it.
        """
        preview = build_panel_preview('F{n}', 'R{n}', 5, set(), set())

        assert len(_names(_faces(preview)[0])) == len(_names(_faces(preview)[1])) == 5
        assert preview[PortPreviewKey.TOTAL.value] == 10

    def test_the_pairing_is_positional(self) -> None:
        """The first front port pairs with the first rear port"""
        pairs = build_panel_preview('F{n}', 'R{n}', 2, set(), set())[PortPreviewKey.PAIRS.value]

        assert pairs == [
            {PortPreviewKey.FRONT.value: 'F1', PortPreviewKey.REAR.value: 'R1'},
            {PortPreviewKey.FRONT.value: 'F2', PortPreviewKey.REAR.value: 'R2'},
        ]

    def test_the_pairing_survives_faces_named_nothing_alike(self) -> None:
        """
        The concept forbids deriving the pairing from the names, and this is why it can

        The two faces here share no naming scheme at all, and the pairing is still correct - because
        it comes from position, and the STORED pairing will be the INTERNAL connection.
        """
        pairs = build_panel_preview(
            'front-{n:02}', 'B{n}', 2, set(), set(),
        )[PortPreviewKey.PAIRS.value]

        assert pairs[0] == {PortPreviewKey.FRONT.value: 'front-01', PortPreviewKey.REAR.value: 'B1'}

    def test_the_two_faces_are_checked_for_collisions_separately(self) -> None:
        """
        A port name is unique WITHIN a face

        A panel's existing front 1 must not be reported as a clash for its new rear 1 - checking the
        two together would make every patch panel look unbuildable.
        """
        preview = build_panel_preview('{n}', '{n}', 1, {'1'}, set())

        assert _existing(_faces(preview)[0]) == ['1']
        assert _existing(_faces(preview)[1]) == []

    def test_identical_syntaxes_are_legal_for_a_panel(self) -> None:
        """
        Front 1 and rear 1 are two different ports

        The unique index keys on the side, so the same name on the two faces is not a duplicate - and
        the preview must not pretend it is.
        """
        preview = build_panel_preview('{n}', '{n}', 2, set(), set())

        assert not preview_has_collisions(preview)

    def test_a_rear_collision_is_reported_on_the_rear_face(self) -> None:
        """The customer has to learn which face to fix"""
        preview = build_panel_preview('F{n}', 'R{n}', 2, set(), {'R2'})

        assert _existing(_faces(preview)[0]) == []
        assert _existing(_faces(preview)[1]) == ['R2']


# -------------------------------------------------------------------------------------------------------------------- #
#                                            the single question a create asks                                         #
# -------------------------------------------------------------------------------------------------------------------- #
class TestPreviewHasCollisions:
    """What step 12 will check before writing, so it cannot disagree with what was shown."""

    def test_a_clean_preview_has_none(self) -> None:
        """The ordinary case"""
        assert preview_has_collisions(build_standard_preview('Gi0/{n}', 3, set())) is False

    def test_a_duplicate_counts(self) -> None:
        """A syntax repeating itself would be refused mid-batch by the unique index"""
        assert preview_has_collisions(build_standard_preview('fixed', 2, set())) is True

    def test_an_existing_name_counts(self) -> None:
        """So does a clash with a port that is already there"""
        assert preview_has_collisions(build_standard_preview('Gi0/{n}', 2, {'Gi0/1'})) is True

    def test_a_collision_on_either_panel_face_counts(self) -> None:
        """A panel is not creatable if either of its faces is blocked"""
        assert preview_has_collisions(
            build_panel_preview('F{n}', 'R{n}', 2, set(), {'R1'}),
        ) is True

    def test_an_empty_preview_has_none(self) -> None:
        """Nothing to collide"""
        assert preview_has_collisions({}) is False


# -------------------------------------------------------------------------------------------------------------------- #
#                                                    constants                                                         #
# -------------------------------------------------------------------------------------------------------------------- #
@pytest.mark.parametrize('enum_cls,expected', [
    (PortPreviewKey, {
        'SIDE': 'side', 'NAMES': 'names', 'COLLISIONS': 'collisions', 'FACES': 'faces',
        'PAIRS': 'pairs', 'TOTAL': 'total', 'FRONT': 'front', 'REAR': 'rear',
    }),
    (PortCollisionKey, {'DUPLICATES': 'duplicates', 'EXISTING': 'existing'}),
], ids=['preview', 'collision'])
def test_the_response_keys_are_pinned(enum_cls, expected: dict) -> None:
    """The preview document is a frontend contract - the assistant renders straight from it"""
    assert {member.name: member.value for member in enum_cls} == expected
