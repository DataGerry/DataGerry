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
This module provides the predefined CmdbExtendableOptions required for Port Connectivity

Four option lists back the select fields of a port and of a cable connection. Every value here ships
as ``predefined``; a customer extends each list through the ordinary extendable-option routes, which
is what the concept means by calling these fields customizable. The lists are starting points, not
closed vocabularies - they cover what is common today and are deliberately not exhaustive
"""
from typing import Any

from cmdb.models.extendable_option_model import OptionType, ExtendableOptionKey
# -------------------------------------------------------------------------------------------------------------------- #

# Operational state of a port, as named by the concept - a closed list of three, unlike the other
# three lists it is not an open-ended set. NOT the same thing as 'connected', which is computed on
# read from the port's connections and is never stored
DEFAULT_PORT_STATUS_VALUES: tuple[str, ...] = (
    'Up',
    'Down',
    'Disabled',
)

# Physical port form factor, ordered copper -> transceiver cages by speed -> fibre connectors.
# The bare 'QSFP' the concept names is deliberately absent: it is not a form factor on its own, and
# QSFP+ (40G), QSFP28 (100G), QSFP56 (200G) and QSFP-DD are not interchangeable. The four fibre
# connectors are here because a patch-panel port IS a coupler rather than a transceiver cage, and
# patch panels are a first-class citizen of this feature
DEFAULT_PORT_TYPE_VALUES: tuple[str, ...] = (
    'RJ45',
    'SFP',
    'SFP+',
    'SFP28',
    'QSFP+',
    'QSFP28',
    'QSFP56',
    'QSFP-DD',
    'OSFP',
    'LC',
    'SC',
    'ST',
    'MPO/MTP',
)

# Link speed, ascending. Written in the short form the industry uses for a PORT ('a 25G port'),
# which also keeps it aligned with the form-factor names that encode the same number - SFP28 is 25G,
# QSFP28 is 100G. 2.5G/5G are the NBASE-T rungs modern access points and desktops run at; 200G and
# above are past the concept's 100G ceiling but shipping
DEFAULT_PORT_SPEED_VALUES: tuple[str, ...] = (
    '10M',
    '100M',
    '1G',
    '2.5G',
    '5G',
    '10G',
    '25G',
    '40G',
    '50G',
    '100G',
    '200G',
    '400G',
    '800G',
)

# Cable medium, ordered copper -> multimode fibre -> singlemode fibre -> direct attach. Cat7/Cat7a
# matter for European installations in particular, and OS1/OS2 are how every campus backbone and
# inter-building run is cabled - singlemode is absent from the concept's list, which names multimode
# only. AOC sits beside DAC in the same racks
DEFAULT_CABLE_TYPE_VALUES: tuple[str, ...] = (
    'Cat5e',
    'Cat6',
    'Cat6a',
    'Cat7',
    'Cat7a',
    'Cat8',
    'OM1',
    'OM2',
    'OM3',
    'OM4',
    'OM5',
    'OS1',
    'OS2',
    'DAC',
    'AOC',
)

# The four lists paired with the OptionType each one populates, in the order they are seeded
PORT_OPTION_VALUES: tuple[tuple[OptionType, tuple[str, ...]], ...] = (
    (OptionType.PORT_STATUS, DEFAULT_PORT_STATUS_VALUES),
    (OptionType.PORT_TYPE, DEFAULT_PORT_TYPE_VALUES),
    (OptionType.PORT_SPEED, DEFAULT_PORT_SPEED_VALUES),
    (OptionType.CABLE_TYPE, DEFAULT_CABLE_TYPE_VALUES),
)

# -------------------------------------------------------------------------------------------------------------------- #

def get_default_port_extendable_options() -> list[dict[str, Any]]:
    """
    Returns the predefined CmdbExtendableOptions for Port Connectivity

    Used by both delivery paths: CollectionValidator seeds them into a freshly created
    extendable-option collection, and the Port Connectivity updater inserts the ones an existing
    installation is missing. Building the documents in one place is what keeps the two in step

    Returns:
        list[dict[str, Any]]: The default Port Connectivity CmdbExtendableOptions as documents
    """
    return [
        {
            ExtendableOptionKey.VALUE: value,
            ExtendableOptionKey.OPTION_TYPE: option_type,
            ExtendableOptionKey.PREDEFINED: True,
        }
        for option_type, values in PORT_OPTION_VALUES
        for value in values
    ]
