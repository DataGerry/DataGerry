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
import { PortDeviceKind } from '../../models/port-bulk.types';
import { ChoiceCard } from '../choice-card-group/choice-card-group.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** One device kind, as the first step offers it. */
export type DeviceKindChoice = ChoiceCard<PortDeviceKind>;


export const DEVICE_KIND_CHOICES: readonly DeviceKindChoice[] = [
    {
        value: PortDeviceKind.PATCH_PANEL,
        label: 'Patch panel',
        icon: 'fas fa-grip-horizontal',
        text: 'Front and rear ports, paired automatically.'
    },
    {
        value: PortDeviceKind.STANDARD,
        label: 'Standard network device',
        icon: 'fas fa-server',
        text: 'Single ports, no internal pairing.'
    }
];


/** Empty while nothing is picked yet, which is what the preview heading then shows. */
export function labelOfDeviceKind(kind: PortDeviceKind | null): string {
    return DEVICE_KIND_CHOICES.find((choice) => choice.value === kind)?.label ?? '';
}
