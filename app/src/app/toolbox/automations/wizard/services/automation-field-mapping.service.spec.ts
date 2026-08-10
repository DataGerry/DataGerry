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
import { AutomationField } from '../models/automation-definition.model';
import { TargetField } from '../models/target-catalog.model';
import { AutomationFieldMappingService } from './automation-field-mapping.service';
/* ------------------------------------------------------------------------------------------------------------------ */

function field(name: string, label = name, type = 'text'): AutomationField {
    return { name, label, type };
}


function target(path: string, type = 'string'): TargetField {
    return { path, name: path.split('.').pop() ?? path, type };
}


describe('AutomationFieldMappingService', () => {
    let service: AutomationFieldMappingService;

    beforeEach(() => {
        service = new AutomationFieldMappingService();
    });


    it('matches on the technical name with full confidence', () => {
        const result = service.suggest([field('hostname')], [target('hostname'), target('other')]);

        expect(result[0].target).toBe('hostname');
        expect(result[0].matchedOn).toBe('name');
        expect(result[0].sources[0].confidence).toBe(1);
    });


    it('matches on the label when the name differs', () => {
        const result = service.suggest([field('f_text_1', 'serial')], [target('serial')]);

        expect(result[0].target).toBe('serial');
        expect(result[0].matchedOn).toBe('label');
    });


    it('bridges known synonyms across systems', () => {
        // A DataGerry 'hostname' is i-doit's 'title' - no string similarity would find that.
        const result = service.suggest([field('hostname')], [target('title')]);

        expect(result[0].target).toBe('title');
        expect(result[0].matchedOn).toBe('alias');
    });


    it('ignores separators and case when comparing', () => {
        const result = service.suggest([field('serial_number')], [target('serialNumber')]);

        expect(result[0].target).toBe('serialNumber');
    });


    it('leaves a field unmapped rather than guessing badly', () => {
        const result = service.suggest([field('inventory_number')], [target('zzz_unrelated')]);

        // A field nothing matches produces no entry at all; there is no target to key it by.
        expect(result).toEqual([]);
    });


    it('never maps two source fields onto the same target', () => {
        const result = service.suggest([field('title'), field('name')], [target('title')]);

        // The second field finds nothing left, so it produces no entry rather than an empty one.
        expect(result.map(entry => entry.target)).toEqual(['title']);
    });


    it('keeps manual entries and their targets when filling gaps', () => {
        const existing = [
            { target: 'custom_field', sources: [{ field: 'hostname', origin: 'manual' as const, confidence: 1 }] }
        ];

        const filled = service.fillGaps(
            existing,
            [field('hostname'), field('serial')],
            [target('custom_field'), target('serial')]
        );

        expect(filled[0].target).toBe('custom_field');
        expect(filled[0].sources[0].origin).toBe('manual');
        expect(filled[1].target).toBe('serial');
    });


    /* A field the user took away must not come back on the next pass. */
    it('leaves a field the user deliberately cleared alone', () => {
        const filled = service.fillGaps([], [field('serial')], [target('serial')], ['serial']);

        expect(filled).toEqual([]);
    });


    it('adds an entry for a field picked after the mapping was made', () => {
        const existing = [
            { target: 'title', sources: [{ field: 'hostname', origin: 'manual' as const, confidence: 1 }] }
        ];

        const filled = service.fillGaps(
            existing,
            [field('hostname'), field('serial')],
            [target('title'), target('serial')]
        );

        expect(filled.length).toBe(2);
        expect(filled[1].sources[0].field).toBe('serial');
        expect(filled[1].target).toBe('serial');
    });


    it('drops an entry whose field is no longer selected', () => {
        const existing = [
            { target: 'title', sources: [{ field: 'hostname', origin: 'manual' as const, confidence: 1 }] },
            { target: 'serial', sources: [{ field: 'serial', origin: 'manual' as const, confidence: 1 }] }
        ];

        const pruned = service.prune(existing, [field('hostname')], [target('title')]);

        expect(pruned.length).toBe(1);
        expect(pruned[0].sources[0].field).toBe('hostname');
    });


    it('names the fields that feed nothing', () => {
        expect(service.unassigned(
            [{ target: 'title', sources: [{ field: 'hostname', origin: 'auto', confidence: 1 }] }],
            [field('hostname'), field('serial')]
        )).toEqual(['serial']);
    });

});
