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
import { PortOptionType } from 'src/app/framework/models/port-option-type';
/* ------------------------------------------------------------------------------------------------------------------ */

/** Labels ExtendableOptionManagerComponent needs to talk about one option type. */
export interface ManageableOptionType {
    optionType: string;
    manageLabel: string;
    modalTitle: string;
    itemLabel: string;
    itemLabelPlural: string;
}

/** The option types a user may extend from the field that uses them; anything absent stays read-only. */
export const MANAGEABLE_OPTION_TYPES: Readonly<Record<string, ManageableOptionType>> = {
    [PortOptionType.STATUS]: {
        optionType: PortOptionType.STATUS,
        manageLabel: 'Manage Statuses',
        modalTitle: 'Manage Port Statuses',
        itemLabel: 'Port Status',
        itemLabelPlural: 'Port Statuses'
    },
    [PortOptionType.PORT_TYPE]: {
        optionType: PortOptionType.PORT_TYPE,
        manageLabel: 'Manage Port Types',
        modalTitle: 'Manage Port Types',
        itemLabel: 'Port Type',
        itemLabelPlural: 'Port Types'
    },
    [PortOptionType.SPEED]: {
        optionType: PortOptionType.SPEED,
        manageLabel: 'Manage Speeds',
        modalTitle: 'Manage Port Speeds',
        itemLabel: 'Port Speed',
        itemLabelPlural: 'Port Speeds'
    }
};


export function manageableOptionType(optionType: string): ManageableOptionType | null {
    return optionType ? MANAGEABLE_OPTION_TYPES[optionType] ?? null : null;
}
