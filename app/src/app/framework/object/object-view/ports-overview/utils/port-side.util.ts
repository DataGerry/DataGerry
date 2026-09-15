/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.
*
* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { PortSide } from '../models/ports-overview.types';
/* ------------------------------------------------------------------------------------------------------------------ */

/** How a panel face reads next to a port name. SINGLE has no face, so it stays empty. */
const SIDE_LABELS: Record<PortSide, string> = {
    [PortSide.SINGLE]: '',
    [PortSide.FRONT]: 'Front',
    [PortSide.REAR]: 'Rear'
};

/** The same face as the heading of an option group, where the badge's singular would not read. */
const SIDE_GROUPS: Record<PortSide, string> = {
    [PortSide.SINGLE]: 'Ports',
    [PortSide.FRONT]: 'Front ports',
    [PortSide.REAR]: 'Rear ports'
};


/** An unknown or missing side reads as an ordinary device port, matching the stored default. */
export function normalizeSide(side: PortSide | null | undefined): PortSide {
    return side === PortSide.FRONT || side === PortSide.REAR ? side : PortSide.SINGLE;
}


export function portSideLabel(side: PortSide | null | undefined): string {
    return SIDE_LABELS[normalizeSide(side)];
}


export function portSideGroup(side: PortSide | null | undefined): string {
    return SIDE_GROUPS[normalizeSide(side)];
}
