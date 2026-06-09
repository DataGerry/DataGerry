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
import { Provider } from '@angular/core';

import { CmdbMode } from '../../../modes.enum';
import { FIELD_COMPONENT_OVERRIDES } from '../../fields/field-component-overrides';
import { MDS_ROW_VALIDATORS } from '../../sections/multi-data-section/mds-row-validator';
import { IpamSubnetSelectComponent } from './components/ipam-subnet-select/ipam-subnet-select.component';
import { IPAM_INTERFACE_FIELD_NAMES } from './models/interface-fields';
import { InterfaceMdsValidatorService } from './services/interface-mds-validator.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Registers IPAM-interface plugins against the generic render/MDS extension points so the
 * render and MDS components can pick them up without importing IPAM directly. Add this to the
 * providers of the module that owns rendering (RenderModule).
 */
export const IPAM_INTERFACE_PROVIDERS: ReadonlyArray<Provider> = [
    {
        provide: MDS_ROW_VALIDATORS,
        useExisting: InterfaceMdsValidatorService,
        multi: true
    },
    {
        // Swap the generic ref dropdown for the family-aware network picker, but only while
        // editing - the read-only View keeps the standard reference rendering.
        provide: FIELD_COMPONENT_OVERRIDES,
        useValue: {
            fieldName: IPAM_INTERFACE_FIELD_NAMES.SUBNET,
            component: IpamSubnetSelectComponent,
            modes: [CmdbMode.Create, CmdbMode.Edit, CmdbMode.Bulk]
        },
        multi: true
    }
];
