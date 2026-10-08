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
import {
    declaredVariables,
    GqlSyntaxError,
    listPathsOf,
    looksLikeList,
    parseGraphql,
    printGraphql,
    responseFieldsOf,
    schemaFieldAt,
    schemaFromIntrospection,
    selectedPaths,
    toggleField
} from './graphql-query.model';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The query JDisc's invoker documents, as people write it. */
const JDISC = `query Devices($name: String!) {
  devices {
    # every device
    findAll(name: $name, filter: { os: "Linux, Windows" }) @include(if: true) {
      id
      label: name
      serialNumber
      operatingSystem { osVersion }
      ... on Device { ip }
    }
  }
}`;


describe('graphql-query.model', () => {

    it('reads fields, aliases, arguments, directives and inline fragments', () => {
        const document = parseGraphql(JDISC);
        const findAll = document.selections[0].children![0];

        expect(document.header).toBe('query Devices($name: String!)');
        expect(findAll.name).toBe('findAll');
        expect(findAll.args).toBe('(name: $name, filter: { os: "Linux, Windows" })');
        expect(findAll.directives).toBe('@include(if: true)');
        expect(findAll.children!.map(child => child.alias ?? child.name))
            .toEqual(['id', 'label', 'serialNumber', 'operatingSystem', '... on Device']);
    });


    it('works out the answer, with lists where they are said to be and fragments merged in', () => {
        const document = parseGraphql(JDISC);

        expect(responseFieldsOf(document, path => path === 'devices.findAll')).toEqual({
            data: {
                devices: {
                    findAll: [{
                        id: '',
                        label: '',
                        serialNumber: '',
                        operatingSystem: { osVersion: '' },
                        ip: ''
                    }]
                }
            }
        });
    });


    it('prints braces apart from their content, so nothing reads as a {placeholder}', () => {
        const printed = printGraphql(parseGraphql('{devices{findAll{id}}}'));

        expect(printed).toBe('{\n  devices {\n    findAll {\n      id\n    }\n  }\n}');
        expect(printed).not.toMatch(/\{\w+\}/);
    });


    it('round-trips what it printed', () => {
        const once = printGraphql(parseGraphql(JDISC));

        expect(printGraphql(parseGraphql(once))).toBe(once);
    });


    it('names the line a syntax error is on', () => {
        expect(() => parseGraphql('{\n  devices {\n    findAll {\n      id\n')).toThrowError(GqlSyntaxError, /Line \d+/);
        expect(() => parseGraphql('{ devices { 1abc } }')).toThrowError(/field name/);
    });


    it('lists the variables the operation declares', () => {
        expect(declaredVariables(parseGraphql(JDISC))).toEqual(['name']);
        expect(declaredVariables(parseGraphql('{ a }'))).toEqual([]);
    });


    it('adds a field along with its parents, and takes empty parents out with it', () => {
        let document = parseGraphql('{ devices { findAll { id } } }');

        document = toggleField(document, ['devices', 'findAll', 'name'], true);
        expect(selectedPaths(document).has('devices.findAll.name')).toBeTrue();

        document = toggleField(document, ['devices', 'findAll', 'name'], true);
        document = toggleField(document, ['devices', 'findAll', 'id'], true);
        expect(document.selections).toEqual([]);
    });


    it('reads list paths back out of a stored answer', () => {
        expect(listPathsOf({ data: { devices: { findAll: [{ id: '', ips: [{ a: '' }] }] } } }))
            .toEqual(['devices.findAll', 'devices.findAll.ips']);
    });


    it('guesses JDisc\'s list without taking its namespace for one', () => {
        expect(looksLikeList('findAll')).toBeTrue();
        expect(looksLikeList('devices')).toBeFalse();
    });


    it('cuts an introspection answer down to types, fields and list-ness', () => {
        const schema = schemaFromIntrospection(JSON.stringify({
            data: {
                __schema: {
                    queryType: { name: 'Query' },
                    mutationType: null,
                    types: [
                        { kind: 'OBJECT', name: 'Query', fields: [
                            { name: 'devices', args: [], type: { kind: 'OBJECT', name: 'DeviceQueries' } }
                        ] },
                        { kind: 'OBJECT', name: 'DeviceQueries', fields: [
                            { name: 'findAll', args: [{ name: 'name' }], type: {
                                kind: 'NON_NULL', name: null, ofType: { kind: 'LIST', name: null, ofType: { kind: 'OBJECT', name: 'Device' } }
                            } }
                        ] },
                        { kind: 'OBJECT', name: 'Device', fields: [
                            { name: 'id', args: [], type: { kind: 'SCALAR', name: 'ID' } }
                        ] },
                        { kind: 'SCALAR', name: 'ID', fields: null },
                        { kind: 'OBJECT', name: '__Type', fields: [] }
                    ]
                }
            }
        }));

        expect(schemaFieldAt(schema, 'Query', ['devices', 'findAll'])).toEqual({
            type: 'Device', list: true, leaf: false, args: ['name']
        });
        expect(schemaFieldAt(schema, 'Query', ['devices', 'findAll', 'id'])?.leaf).toBeTrue();
        expect(schema.types['__Type']).toBeUndefined();
        expect(() => schemaFromIntrospection('{"x": 1}')).toThrowError(/No schema/);
    });
});
