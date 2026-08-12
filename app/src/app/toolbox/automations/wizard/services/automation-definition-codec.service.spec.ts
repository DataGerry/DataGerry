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
import { createEmptyAutomationDefinition } from '../models/automation-definition.model';
import { AutomationDefinitionCodecService } from './automation-definition-codec.service';
/* ------------------------------------------------------------------------------------------------------------------ */

describe('AutomationDefinitionCodecService', () => {
    let service: AutomationDefinitionCodecService;

    beforeEach(() => {
        service = new AutomationDefinitionCodecService();
    });


    it('round-trips a definition and keeps the human text separate', () => {
        const definition = createEmptyAutomationDefinition();
        definition.name = 'Sync servers';
        definition.objectType = { typeId: 7, name: 'server', label: 'Server' };
        definition.fields = [{ name: 'hostname', label: 'Hostname', type: 'text' }];

        const encoded = service.encode('Keeps our servers in sync', definition);
        const decoded = service.decode(encoded);

        expect(decoded.description).toBe('Keeps our servers in sync');
        expect(decoded.definition?.name).toBe('Sync servers');
        expect(decoded.definition?.objectType.typeId).toBe(7);
        expect(decoded.definition?.fields.length).toBe(1);
    });


    it('survives umlauts and a literal comment terminator in the description', () => {
        const definition = createEmptyAutomationDefinition();
        definition.name = 'Größenprüfung --> Ziel';

        const encoded = service.encode('Beschreibung mit Umlauten äöü und --> darin', definition);
        const decoded = service.decode(encoded);

        expect(decoded.description).toBe('Beschreibung mit Umlauten äöü und --> darin');
        expect(decoded.definition?.name).toBe('Größenprüfung --> Ziel');
    });


    it('replaces an existing block instead of appending a second one', () => {
        const definition = createEmptyAutomationDefinition();
        definition.name = 'First';

        const once = service.encode('Text', definition);
        definition.name = 'Second';
        const twice = service.encode(once, definition);

        expect(twice.match(/dg-automation/g)?.length).toBe(1);
        expect(service.decode(twice).definition?.name).toBe('Second');
        expect(service.decode(twice).description).toBe('Text');
    });


    it('reports no definition for a description written by the previous editor', () => {
        const decoded = service.decode('A plain description with no wizard block');

        expect(decoded.definition).toBeNull();
        expect(decoded.description).toBe('A plain description with no wizard block');
        expect(service.hasDefinition('A plain description with no wizard block')).toBeFalse();
    });


    it('treats a corrupted block as absent so the automation stays openable', () => {
        const decoded = service.decode('Text\n<!--dg-automation:v1:not-valid-base64!!-->');

        expect(decoded.definition).toBeNull();
    });


    it('ignores a block written by a newer wizard version', () => {
        const decoded = service.decode('Text\n<!--dg-automation:v99:eyJuYW1lIjoiWCJ9-->');

        expect(decoded.definition).toBeNull();
        expect(decoded.description).toBe('Text');
    });


    it('flags an encoded description that outgrows the size budget', () => {
        const definition = createEmptyAutomationDefinition();
        definition.fields = Array.from({ length: 2000 }, (_unused, index) => ({
            name: `field_${index}`,
            label: `Field ${index}`,
            type: 'text'
        }));

        expect(service.exceedsSizeBudget(service.encode('', definition))).toBeTrue();
    });


    /*
     * Reopening an automation written before the sequence and the target-keyed mapping existed.
     *
     * The stored block is whatever that version wrote; nothing rewrites it in place, so every
     * version the wizard ever wrote has to read back into the shape it works with now - otherwise
     * an older automation opens with its assignment silently emptied.
     */
    it('reads an automation stored in the older shape', () => {
        const stored = {
            version: 1,
            name: 'Sync servers',
            direction: 'outgoing',
            objectType: { typeId: 4, name: 'server', label: 'Server' },
            fields: [{ name: 'hostname', label: 'Hostname', type: 'text' }],
            target: { connectorId: 10, connectorTitle: 'i-doit', invokerName: 'i-doit', operation: 'create' },
            mapping: [
                { source: 'hostname', target: 'params.title', origin: 'manual', confidence: 1 },
                { source: '$public_id', target: 'params.title', origin: 'auto', confidence: 0.4 },
                // A field the user cleared: a source, and no target at all.
                { source: 'serial', target: '', origin: 'auto', confidence: 0 }
            ]
        };
        const description = service.encode('Written by an older wizard', stored as any);
        const decoded = service.decode(description);
        const definition = decoded.definition!;

        expect(definition.name).toBe('Sync servers');

        // One entry per target, holding both fields that write it, in the order they were stored.
        expect(definition.mapping.length).toBe(1);
        expect(definition.mapping[0].target).toBe('params.title');
        expect(definition.mapping[0].sources.map(source => source.field))
            .toEqual(['hostname', '$public_id']);

        // The cleared field stays cleared rather than being suggested a target again.
        expect(definition.unmapped).toEqual(['serial']);

        // Everything the older shape knew nothing about reads back as empty, not as undefined.
        expect(definition.extras).toEqual([]);
        expect(definition.overrides).toEqual({});
        expect(definition.matching.identifyBy).toBe('');
    });
});
