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
import { deviceKindChoicesFor } from './port-device-kinds';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('port-device-kinds', () => {
    const disabledKinds = (kind: PortDeviceKind | null): PortDeviceKind[] =>
        deviceKindChoicesFor(kind).filter((choice) => choice.disabled).map((choice) => choice.value);

    it('offers everything while the object has no ports', () => {
        expect(disabledKinds(null)).toEqual([]);
    });

    it('rules out a patch panel once the object has standard ports', () => {
        expect(disabledKinds(PortDeviceKind.STANDARD)).toEqual([PortDeviceKind.PATCH_PANEL]);
    });

    it('rules out standard ports on a patch panel', () => {
        expect(disabledKinds(PortDeviceKind.PATCH_PANEL)).toEqual([PortDeviceKind.STANDARD]);
    });

    it('says why a choice is disabled', () => {
        const panel = deviceKindChoicesFor(PortDeviceKind.STANDARD)
            .find((choice) => choice.value === PortDeviceKind.PATCH_PANEL);

        expect(panel.disabledReason).toContain('Delete them first');
    });
});
