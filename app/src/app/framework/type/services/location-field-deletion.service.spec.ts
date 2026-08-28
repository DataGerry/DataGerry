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
import { CmdbTypeSection } from '../../models/cmdb-type';
import { LocationFieldDeletionService } from './location-field-deletion.service';
import { BuilderDeletionGuard } from 'src/app/framework/builder/services/builder-deletion-guard';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * The builder calls this service through the BuilderDeletionGuard seam, passing the model's flat
 * field list. The scenario specs stub that call, so nothing else exercises the resolution itself -
 * which is how a signature drift once left the section guard silently returning false.
 */
describe('LocationFieldDeletionService — section location resolution', () => {

    let service: LocationFieldDeletionService;

    const locationField = { name: 'dg_location', type: 'location' };
    const textField = { name: 'hostname', type: 'text' };

    function section(fields: Array<any>): CmdbTypeSection {
        return { name: 'sec', label: 'Section', type: 'section', fields } as CmdbTypeSection;
    }

    beforeEach(() => {
        service = new LocationFieldDeletionService(null as any, null as any);
    });

    it('resolves a location field referenced by NAME against the flat field list', () => {
        expect(service.sectionContainsLocationField(
            section(['hostname', 'dg_location']), [textField, locationField]
        )).toBeTrue();
    });

    it('resolves a location field that is already hydrated as an object', () => {
        expect(service.sectionContainsLocationField(
            section([textField, locationField]), [textField, locationField]
        )).toBeTrue();
    });

    it('is false for a section holding no location field', () => {
        expect(service.sectionContainsLocationField(
            section(['hostname']), [textField, locationField]
        )).toBeFalse();
    });

    it('is false for an empty section, and tolerates a missing field list', () => {
        expect(service.sectionContainsLocationField(section([]), [locationField])).toBeFalse();
        expect(service.sectionContainsLocationField(section(['dg_location']), null as any)).toBeFalse();
    });

    it('does not treat a whole type instance as the field list', () => {
        // Guards the exact drift that broke this: the caller passes the flat field ARRAY, so a
        // `{ fields: [...] }` wrapper must NOT resolve. If someone reverts the signature to take a
        // CmdbType, the first assertion above starts failing and this one keeps passing.
        expect(service.sectionContainsLocationField(
            section(['dg_location']), { fields: [locationField] } as any
        )).toBeFalse();
    });

    it('satisfies the BuilderDeletionGuard contract structurally', () => {
        const guard: BuilderDeletionGuard = service;

        expect(typeof guard.isLocationField).toBe('function');
        expect(typeof guard.sectionContainsLocationField).toBe('function');
        expect(typeof guard.canDelete).toBe('function');
    });
});
