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
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Port Connectivity has no license key of its own; it ships with IPAM. */
export const PORTS_LICENSE_FEATURE = LicenseFeature.Ipam;


/** What the license leaves of Port Connectivity. Cloud is always `FULL`. */
export enum PortsAccess {
    /** Every action. */
    FULL = 'FULL',
    /** An expired license: existing ports and the cabling stay readable and editable, nothing is added. */
    LAPSED = 'LAPSED',
    /** No license: no ports and no cabling view. */
    LOCKED = 'LOCKED'
}


export function portsAccessOf(licensed: boolean, expired: boolean): PortsAccess {
    if (licensed) {
        return PortsAccess.FULL;
    }

    return expired ? PortsAccess.LAPSED : PortsAccess.LOCKED;
}
