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
import { AutomationDefinition, createEmptyAutomationDefinition } from '../models/automation-definition.model';
import { AutomationCompilerService, AutomationCompileContext } from './automation-compiler.service';
import { TargetCatalogService } from './target-catalog.service';
/* ------------------------------------------------------------------------------------------------------------------ */

/**
 * Fixtures modelled on the reference payloads captured from a running installation
 * (OpenCelium_Connection_*_Request.json), reduced to the operations these tests exercise.
 *
 * The full-payload comparison against those files lives in
 * app/tools/verify-automation-compiler, which needs no browser. These specs lock in the
 * structural contract so a regression is caught without the capture files at hand.
 */
function idoitInvoker(): any {
    return {
        name: 'i-doit',
        description: 'i-doit',
        hint: '',
        icon: '',
        data: { url: 'http://example/src/jsonrpc.php', apikey: '' },
        auth: 'token',
        operations: [
            { name: 'login', type: 'test', request: {}, response: {} },
            {
                name: 'cmdb.objects.read',
                type: '',
                request: {
                    endpoint: '{url}',
                    method: 'POST',
                    header: { 'Content-Type': 'application/json' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: {
                            method: 'cmdb.objects.read',
                            params: {
                                filter: { sysid: '', type: [], title: '' },
                                apikey: '{apikey}',
                                limit: ''
                            }
                        }
                    }
                },
                response: {
                    success: {
                        status: '200',
                        body: {
                            type: 'object',
                            format: 'json',
                            data: 'raw',
                            fields: { result: [{ id: '', title: '', sysid: '' }], id: '' }
                        }
                    },
                    fail: { status: '200', body: null }
                }
            },
            {
                name: 'cmdb.object.update',
                type: '',
                request: {
                    endpoint: '{url}',
                    method: 'POST',
                    header: { 'Content-Type': 'application/json' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: {
                            method: 'cmdb.object.update',
                            id: '1',
                            params: { id: '', title: '', apikey: '{apikey}' }
                        }
                    }
                },
                response: {
                    success: { status: '200', body: { fields: { result: { id: '' } } } },
                    fail: { status: '200', body: null }
                }
            },
            {
                name: 'cmdb.object.create',
                type: '',
                request: {
                    endpoint: '{url}',
                    method: 'POST',
                    header: { 'Content-Type': 'application/json' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: {
                            method: 'cmdb.object.create',
                            params: { type: '', title: '', category: '', apikey: '{apikey}' }
                        }
                    }
                },
                response: {
                    success: { status: '200', body: { fields: { result: { id: '' } } } },
                    fail: { status: '200', body: null }
                }
            }
        ]
    };
}


function dataGerryInvoker(): any {
    return {
        name: 'DataGerryCloud',
        description: 'DataGerry',
        hint: '',
        icon: '',
        data: { url: '', username: '' },
        auth: 'basic',
        operations: [
            { name: 'GetCategories', type: 'test', request: {}, response: {} },
            {
                name: 'AddObject',
                type: '',
                request: {
                    endpoint: '{url}/rest/objects/',
                    method: 'POST',
                    header: { Authorization: '{token}' },
                    body: {
                        type: 'object',
                        format: 'json',
                        data: 'raw',
                        fields: { type_id: '', version: '', active: '', fields: [] }
                    }
                },
                response: {
                    success: { status: '200', body: { type: 'array', format: 'json', data: 'raw', fields: {} } },
                    fail: { status: '401', body: null }
                }
            },
            {
                name: 'GetObjects',
                type: '',
                request: { endpoint: '{url}/rest/objects/', method: 'GET', header: {}, body: {} },
                response: {
                    success: {
                        status: '200',
                        body: { fields: { results: [{ public_id: '', fields: [] }], count: '' } }
                    },
                    fail: { status: '401', body: null }
                }
            }
        ]
    };
}


function context(): AutomationCompileContext {
    return {
        internalConnector: {
            connectorId: 9,
            title: 'DataGerryInternal',
            icon: '',
            invoker: dataGerryInvoker()
        },
        targetConnector: { connectorId: 10, title: 'i-doit Demo', icon: '', invoker: idoitInvoker() },
        objectTypeFieldOrder: ['hostname', 'serial']
    };
}


/** The reference scenario: i-doit is read, DataGerry is written. */
function incomingDefinition(): AutomationDefinition {
    const definition = createEmptyAutomationDefinition();
    definition.name = 'My Automation';
    definition.direction = 'incoming';
    definition.objectType = { typeId: 1, name: 'hardware', label: 'Hardware' };
    definition.fields = [{ name: 'id', label: 'ID', type: 'text' }];
    definition.target = {
        connectorId: 10,
        connectorTitle: 'i-doit Demo',
        invokerName: 'i-doit',
        operation: 'create',
        remoteObjectTypeId: '10'
    };
    definition.mapping = [{ target: 'version', sources: [{ field: 'id', origin: 'auto', confidence: 1 }] }];
    definition.advanced.batchSize = 1;

    return definition;
}


describe('AutomationCompilerService', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });

    /* --------------------------------------------------- VALIDATION -------------------------------------------------- */

    describe('validate', () => {
        it('accepts the reference scenario', () => {
            expect(compiler.validate(incomingDefinition(), context())).toEqual([]);
        });


        it('rejects a trigger the compiler cannot execute yet', () => {
            const definition = incomingDefinition();
            definition.trigger.type = 'webhook';

            expect(compiler.validate(definition, context())
                .some(error => error.includes('cannot be executed yet'))).toBeTrue();
        });


        it('requires a cron expression for a scheduled trigger', () => {
            const definition = incomingDefinition();
            definition.trigger = { type: 'scheduled', cronExp: '' };

            expect(compiler.validate(definition, context())
                .some(error => error.includes('cron expression'))).toBeTrue();
        });


        it('requires a name, an object type, fields, a target and a mapping', () => {
            const empty = createEmptyAutomationDefinition();
            const errors = compiler.validate(empty, context());

            expect(errors.some(error => error.includes('name'))).toBeTrue();
            expect(errors.some(error => error.includes('object type'))).toBeTrue();
            expect(errors.some(error => error.includes('at least one field'))).toBeTrue();
            expect(errors.some(error => error.includes('target system'))).toBeTrue();
        });


        it('reports when nothing has been mapped', () => {
            const definition = incomingDefinition();
            definition.mapping = [{ target: '', sources: [{ field: 'id', origin: 'auto', confidence: 0 }] }];

            expect(compiler.validate(definition, context())
                .some(error => error.includes('Map at least one field'))).toBeTrue();
        });
    });

    /* -------------------------------------------------- CONNECTION --------------------------------------------------- */

    describe('compileForCreate', () => {
        it('reads the source and writes the target according to the direction', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            // Both systems' methods share one list now; each names its own connector.
            expect(payload.connection.fromConnector.connectorId).toBe(-1);
            expect(payload.connection.toConnector).toBeNull();
            expect(payload.connection.fromConnector.methods[0].name).toBe('cmdb.objects.read');
            expect(payload.connection.fromConnector.methods[0].connector.connectorId).toBe(10);
            expect(payload.connection.fromConnector.methods[1].name).toBe('AddObject');
            expect(payload.connection.fromConnector.methods[1].connector.connectorId).toBe(9);
        });


        it('assigns the reference colours and execution indices', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods[0].color).toBe('#FFCFB5');
            expect(payload.connection.fromConnector.methods[0].index).toBe('0');
            expect(payload.connection.fromConnector.methods[1].color).toBe('#C77E7E');
            expect(payload.connection.fromConnector.methods[1].index).toBe('1_0');
        });


        it('labels the read method and leaves the target method unlabelled', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods[0].label).toBe('GetObjects');
            expect('label' in payload.connection.fromConnector.methods[1]).toBeFalse();
        });


        it('wraps the target method in a loop over the source collection', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const loop = payload.connection.fromConnector.operators[0];

            expect(loop.type).toBe('loop');
            expect(loop.expression).toBe('for {%#FFCFB5.(response).body.$.result[*]%}');
            expect(loop.iterator).toBe('i');
            expect(loop.index).toBe('1');
            // Omitted rather than sent as null when nothing restricts the loop, as the captures show.
            expect('condition' in loop).toBeFalse();
        });


        it('writes the source reference into the target request body', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.version)
                .toBe('#FFCFB5.(response).body.$.result[i].id');
        });


        it('records the same pair as a field binding with its enhancement script', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const binding = payload.connection.fieldBinding[0];

            expect(binding.from[0]).toEqual({
                color: '#FFCFB5',
                field: 'body.$.result[i].id',
                type: 'response'
            });
            expect(binding.to[0]).toEqual({ color: '#C77E7E', field: 'body.$.version', type: 'request' });
            expect(binding.enhancement.expertCode).toBe('RESULT_VAR = VAR_0;');
            expect(binding.enhancement.expertVar).toContain('#C77E7E.(request).body.$.version');
            expect(binding.enhancement.expertVar).toContain('#FFCFB5.(response).body.$.result[i].id');
        });


        it('restricts the read to the selected object type and prunes unused filter keys', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const params = payload.connection.fromConnector.methods[0].request.body.fields.params;

            expect(params.filter).toEqual({ type: ['10'] });
        });


        /*
         * The two write the same parameter, so only one of them may. An operation that pages sets
         * its own page size and fetches every page, which is what the setting was trying to
         * approximate.
         */
        it('leaves the page size alone when the read operation pages by itself', () => {
            const paging = context();
            const objectsRead = paging.targetConnector.invoker.operations
                .find((operation: any) => operation.name === 'cmdb.objects.read');
            // What the API actually exposes. The pagination block itself never reaches a client.
            objectsRead.type = 'page';

            const definition = incomingDefinition();
            definition.advanced.batchSize = 250;

            const { payload, warnings } = compiler.compileForCreate(definition, paging);

            expect(payload.connection.fromConnector.methods[0].request.body.fields.params.limit)
                .toBe('');
            expect(warnings.some(warning => warning.includes('fetches every page'))).toBeTrue();
        });


        it('applies the batch size as the read operation page size', () => {
            const definition = incomingDefinition();
            definition.advanced.batchSize = 250;

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[0].request.body.fields.params.limit).toBe('250');
        });


        it('carries no connection id and repeats the title as the name', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect('connectionId' in payload.connection).toBeFalse();
            expect(payload.connection.title).toBe('My Automation');
            expect(payload.connection.name).toBe('My Automation');
        });


        /*
         * The invoker definitions used to travel inside the connection and made up most of its
         * 300 KB. OpenCelium resolves them from the connector now, so sending them back would be
         * both pointless and a way to resend credentials.
         */
        it('names the connector instead of embedding its invoker', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const method = payload.connection.fromConnector.methods[0];

            expect('invoker' in method).toBeFalse();
            expect(method.connector).toEqual({
                connectorId: 10,
                title: 'i-doit Demo',
                icon: null,
                invokerName: 'i-doit'
            });
        });


        it('builds the workflow graph the editor draws from', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const { workflowNodes, workflowEdges } = payload.connection.ui;

            expect(workflowNodes.map(node => node.id))
                .toEqual(['start-1', 'method-0', 'loop-0', 'method-1']);
            expect(workflowNodes.map(node => node.type))
                .toEqual(['start', 'connector', 'loop', 'connector']);
            // The written method runs inside the loop, so it hangs below it instead of continuing.
            expect(workflowNodes[3].position).toEqual({ x: 450, y: 348 });
            expect(workflowEdges.map(edge => edge.id)).toEqual([
                'edge-start-1-method-0-default-left',
                'edge-method-0-loop-0-default-left',
                'edge-loop-0-method-1-bottom-top'
            ]);
        });


        it('repeats the graph as flowcharts and carries edge data only on create', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.ui.flowcharts).toEqual([
                { flowId: 'start-1', x: 120, y: 220 },
                { flowId: 'method-0', x: 285, y: 220 },
                { flowId: 'loop-0', x: 450, y: 220 },
                { flowId: 'method-1', x: 450, y: 348 }
            ]);
            expect(payload.connection.ui.workflowEdges[0].data).toEqual({});
            expect('data' in payload.connection.ui.flowchartEdges[0]).toBeFalse();
        });


        it('restates the method as the editor\'s request form reads it', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());
            const config = payload.connection.ui.workflowNodes[1].data.methodConfig;
            const request = payload.connection.fromConnector.methods[0].request;

            expect(config.url).toBe(request.endpoint);
            expect(config.method).toBe(request.method);
            expect(config.body).toEqual(request.body.fields);
            expect(config.bodyFormat).toBe('json');
            expect(config.name).toBe('cmdb.objects.read');
            expect(config.response.responseId).toBe('response-method-0');
        });


        it('derives the scheduler from the trigger and the advanced settings', () => {
            const definition = incomingDefinition();
            definition.trigger = { type: 'scheduled', cronExp: '0 2 * * *' };
            definition.advanced.loggingEnabled = true;
            definition.active = false;

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.scheduler).toEqual({
                title: 'My Automation',
                debugMode: true,
                status: 0,
                cronExp: '0 2 * * *'
            });
        });


        it('sends no cron expression for a manual trigger', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.scheduler.cronExp).toBe('');
            expect(payload.scheduler.status).toBe(1);
        });
    });

    /* ---------------------------------------------------- UPDATE ----------------------------------------------------- */

    describe('compileForUpdate', () => {
        it('sends the connection id and is otherwise the create payload', () => {
            const created = compiler.compileForCreate(incomingDefinition(), context()).payload.connection;
            const { payload } = compiler.compileForUpdate(incomingDefinition(), context(), 16);
            const { connectionId, ...rest } = payload;

            expect(connectionId).toBe(16);
            // Only the edges' empty `data` separates the two bodies, as the captures show.
            expect(JSON.stringify(rest.fromConnector)).toBe(JSON.stringify(created.fromConnector));
            expect(rest.toConnector).toBeNull();
        });


        it('omits the edge data the create payload carries', () => {
            const { payload } = compiler.compileForUpdate(incomingDefinition(), context(), 16);

            expect('data' in payload.ui.workflowEdges[0]).toBeFalse();
        });


        it('leaves the caller\'s connector objects untouched', () => {
            const shared = context();

            compiler.compileForUpdate(incomingDefinition(), shared, 16);

            expect(shared.targetConnector.invoker.auth).toBe('token');
            expect(shared.internalConnector.invoker.auth).toBe('basic');
        });
    });

    /* -------------------------------------------------- DIRECTIONS --------------------------------------------------- */

    describe('outgoing automations', () => {
        function outgoingDefinition(): AutomationDefinition {
            const definition = incomingDefinition();
            definition.direction = 'outgoing';
            definition.fields = [
                { name: 'hostname', label: 'Hostname', type: 'text' },
                { name: 'serial', label: 'Serial', type: 'text' }
            ];
            definition.mapping = [{ target: 'params.title', sources: [{ field: 'serial', origin: 'manual', confidence: 1 }] }];

            return definition;
        }


        it('reads DataGerry and writes the foreign system', () => {
            const { payload } = compiler.compileForCreate(outgoingDefinition(), context());

            expect(payload.connection.fromConnector.methods[0].name).toBe('GetObjects');
            expect(payload.connection.fromConnector.methods[0].connector.connectorId).toBe(9);
            expect(payload.connection.fromConnector.methods[1].connector.connectorId).toBe(10);
        });


        it('addresses a DataGerry field by its position in the object type', () => {
            const { payload } = compiler.compileForCreate(outgoingDefinition(), context());

            // 'serial' is the second field of the type, so it is fields[1].value.
            expect(payload.connection.fieldBinding[0].from[0].field)
                .toBe('body.$.results[i].fields[1].value');
        });


        it('warns that DataGerry fields are addressed positionally', () => {
            const { warnings } = compiler.compileForCreate(outgoingDefinition(), context());

            expect(warnings.some(warning => warning.includes('position in the object type'))).toBeTrue();
        });


        it('skips a mapped field that is not part of the object type', () => {
            const definition = outgoingDefinition();
            definition.mapping = [
                { target: 'params.title', sources: [{ field: 'not_in_type', origin: 'manual', confidence: 1 }] },
                { target: 'params.category', sources: [{ field: 'serial', origin: 'manual', confidence: 1 }] }
            ];

            const { payload, warnings } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fieldBinding.length).toBe(1);
            expect(warnings.some(warning => warning.includes('not_in_type'))).toBeTrue();
        });


        it('addresses the object id at the top of the object, not inside its fields', () => {
            const definition = outgoingDefinition();
            definition.fields = [...definition.fields, { name: '$public_id', label: 'DataGerry object ID', type: 'number' }];
            definition.mapping = [{ target: 'params.title', sources: [{ field: '$public_id', origin: 'manual', confidence: 1 }] }];

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fieldBinding[0].from[0].field).toBe('body.$.results[i].public_id');
        });
    });

    /* ------------------------------------------------- IDENTIFICATION -------------------------------------------------- */

    describe('identification', () => {
        it('writes the object type as a literal instead of reading it from the source', () => {
            // The reason this exists: objects created in DataGerry must land under the type the user
            // chose, and that type is known to the wizard rather than to the system being read.
            const definition = incomingDefinition();
            definition.fields = [{ name: '$type_id', label: 'DataGerry object type ID', type: 'number' }];
            definition.mapping = [{ target: 'type_id', sources: [{ field: '$type_id', origin: 'manual', confidence: 1 }] }];

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.type_id).toBe('1');
            // A literal is not read from anywhere, so it needs no binding.
            expect(payload.connection.fieldBinding.length).toBe(0);
        });


        it('skips a DataGerry object value when DataGerry is not the side being read', () => {
            const definition = incomingDefinition();
            definition.mapping = [
                { target: 'active', sources: [{ field: '$public_id', origin: 'manual', confidence: 1 }] },
                { target: 'version', sources: [{ field: 'id', origin: 'manual', confidence: 1 }] }
            ];

            const { payload, warnings } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fieldBinding.length).toBe(1);
            expect(warnings.some(warning => warning.includes('DataGerry object ID'))).toBeTrue();
        });
    });

    /* ------------------------------------------------ VALUE ADJUSTMENT ------------------------------------------------- */

    describe('value adjustments', () => {
        function adjusted(script: string, enabled = true): AutomationDefinition {
            const definition = incomingDefinition();
            definition.mapping = [{ target: 'version', sources: [{ field: 'id', origin: 'manual', confidence: 1 }], transform: { enabled, script } }];

            return definition;
        }


        it('wraps the user script around a variable named value', () => {
            const { payload } = compiler.compileForCreate(adjusted('value = value.toUpperCase();'), context());

            expect(payload.connection.fieldBinding[0].enhancement.expertCode)
                .toBe('var value = VAR_0;\nvalue = value.toUpperCase();\nRESULT_VAR = value;');
        });


        it('transfers the value unchanged while the adjustment is switched off', () => {
            const { payload } = compiler.compileForCreate(adjusted('value = value.trim();', false), context());

            expect(payload.connection.fieldBinding[0].enhancement.expertCode).toBe('RESULT_VAR = VAR_0;');
        });


        it('warns about an adjustment that has no content', () => {
            const { payload, warnings } = compiler.compileForCreate(adjusted('   '), context());

            expect(payload.connection.fieldBinding[0].enhancement.expertCode).toBe('RESULT_VAR = VAR_0;');
            expect(warnings.some(warning => warning.includes('no content'))).toBeTrue();
        });
    });

    /* ------------------------------------------------ CORRECTIONS ---------------------------------------------------- */

    /*
     * The sequence is derived, so a call cannot be added - but a foreign API often wants a header or
     * a parameter no field mapping covers, and correcting one is what these carry.
     */
    describe('call corrections', () => {
        it('replaces a header on the call it names', () => {
            const definition = incomingDefinition();
            definition.overrides = { '1_0': { headers: { 'X-Tenant': 'acme' } } };

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[1].request.header['X-Tenant']).toBe('acme');
        });


        it('replaces the endpoint', () => {
            const definition = incomingDefinition();
            definition.overrides = { '1_0': { endpoint: '{url}/v2' } };

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[1].request.endpoint).toBe('{url}/v2');
        });


        it('sets a body value the mapping does not write', () => {
            const definition = incomingDefinition();
            definition.overrides = { '1_0': { body: { 'params.category': 'hardware' } } };

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.params.category)
                .toBe('hardware');
        });


        /* OpenCelium rewrites a bound field on save, so an override there would be dropped. */
        it('reports rather than applies a correction to a field the mapping writes', () => {
            const definition = incomingDefinition();
            definition.overrides = { '1_0': { body: { version: 'by hand' } } };

            const { payload, warnings } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.version)
                .not.toBe('by hand');
            expect(warnings.some(warning => warning.includes('written by the field assignment'))).toBeTrue();
        });


        it('leaves a call nobody corrected alone', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods[1].request.header['X-Tenant']).toBeUndefined();
        });
    });

    /* ------------------------------------------------- MATCHING ------------------------------------------------------ */

    /*
     * An automation that updates or deletes has to find the object in the target system first: it
     * needs that system's own identifier, which nothing in DataGerry knows. The compiler therefore
     * reads the target system, branches on whether it answered with anything, and hands the found
     * identifier to the write.
     */
    describe('matching', () => {
        /* DataGerry is read and i-doit written, which is where a lookup is actually needed. */
        function updating(whenMissing: 'skip' | 'create' = 'skip'): AutomationDefinition {
            const definition = incomingDefinition();
            definition.direction = 'outgoing';
            definition.fields = [{ name: 'hostname', label: 'Hostname', type: 'text' }];
            definition.target.operation = 'update';
            definition.mapping = [
                { target: 'params.title', sources: [{ field: 'hostname', origin: 'manual', confidence: 1 }] }
            ];
            definition.matching = { identifyBy: 'hostname', whenMissing, whenPresent: 'update' };

            return definition;
        }


        it('rejects an update that names no identifying field', () => {
            const definition = updating();
            definition.matching.identifyBy = '';

            expect(compiler.validate(definition, context()))
                .toContain(jasmine.stringContaining('identifies the object'));
        });


        it('reads the target system before it writes', () => {
            const { payload } = compiler.compileForCreate(updating(), context());
            const methods = payload.connection.fromConnector.methods;

            expect(methods.map(method => method.name))
                .toEqual(['GetObjects', 'cmdb.objects.read', 'cmdb.object.update']);
            expect(methods[1].index).toBe('1_0');
            expect(methods[2].index).toBe('1_1_0');
        });


        it('branches on whether the lookup answered with anything', () => {
            const { payload } = compiler.compileForCreate(updating(), context());
            const operators = payload.connection.fromConnector.operators;
            const lookupColor = payload.connection.fromConnector.methods[1].color;

            expect(operators.map(operator => operator.type)).toEqual(['loop', 'if']);
            expect(operators[1].index).toBe('1_1');
            expect(operators[1].expression)
                .toBe(`(\{%${lookupColor}.(response).body.$.result[*]%\} NotEmpty)`);
            expect(operators[1].iterator).toBeNull();
        });


        it('searches by the identifying pair, on the filter the read operation offers', () => {
            const { payload } = compiler.compileForCreate(updating(), context());
            const lookup = payload.connection.fromConnector.methods[1];

            expect(lookup.request.body.fields.params.filter.title)
                .toBe('#FFCFB5.(response).body.$.results[i].fields[0].value');
        });


        /* The one reference in the payload that reads another method's answer instead of the source. */
        it('hands the found identifier to the write', () => {
            const { payload } = compiler.compileForCreate(updating(), context());
            const [, lookup, write] = payload.connection.fromConnector.methods;
            const binding = payload.connection.fieldBinding
                .find(entry => entry.to[0].field === 'body.$.params.id');

            expect(write.request.body.fields.params.id)
                .toBe(`${lookup.color}.(response).body.$.result[0].id`);
            expect(binding?.from[0]).toEqual({
                color: lookup.color,
                field: 'body.$.result[0].id',
                type: 'response'
            });
        });


        it('adds a second branch when a missing object should be created', () => {
            const { payload } = compiler.compileForCreate(updating('create'), context());
            const operators = payload.connection.fromConnector.operators;
            const methods = payload.connection.fromConnector.methods;

            expect(operators.map(operator => operator.index)).toEqual(['1', '1_1', '1_2']);
            expect(operators[1].expression).toContain('IsEmpty');
            expect(operators[2].expression).toContain('NotEmpty');
            expect(methods.map(method => method.index)).toEqual(['0', '1_0', '1_1_0', '1_2_0']);
            expect(methods[2].name).toBe('cmdb.object.create');
            expect(methods[3].name).toBe('cmdb.object.update');
        });


        it('reaches the second branch through the first one\'s miss', () => {
            const { payload } = compiler.compileForCreate(updating('create'), context());
            const edges = payload.connection.ui.workflowEdges;
            const [firstIf, secondIf] = payload.connection.fromConnector.operators.slice(1);

            expect(edges.find(edge => edge.target === secondIf.id))
                .toEqual(jasmine.objectContaining({ source: firstIf.id, sourceHandle: 'false' }));
            expect(edges.filter(edge => edge.sourceHandle === 'true').length).toBe(2);
        });


        it('draws the branches side by side, each with its method below it', () => {
            const { payload } = compiler.compileForCreate(updating('create'), context());
            const byId = new Map(payload.connection.ui.workflowNodes.map(node => [node.id, node.position]));
            const [firstIf, secondIf] = payload.connection.fromConnector.operators.slice(1);

            expect(byId.get(firstIf.id)!.y).toBe(byId.get(secondIf.id)!.y);
            expect(byId.get(secondIf.id)!.x).toBeGreaterThan(byId.get(firstIf.id)!.x);
            expect(byId.get('method-2')!.y).toBeGreaterThan(byId.get(firstIf.id)!.y);
        });


        it('leaves an automation that only adds without a lookup', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.methods.length).toBe(2);
            expect(payload.connection.fromConnector.operators.map(operator => operator.type))
                .toEqual(['loop']);
        });
    });

    /* ------------------------------------------ ADJUSTED FIXED VALUES ------------------------------------------------ */

    /*
     * A fixed value carries no source field, but OpenCelium only runs a script inside a fieldBinding
     * and a fieldBinding insists on a `from`. The compiler therefore names a field the read operation
     * returns anyway and seeds the script with the literal instead of that field's value.
     */
    describe('adjusted fixed values', () => {
        function adjustedConstant(script: string, enabled = true): AutomationDefinition {
            const definition = incomingDefinition();
            definition.fields = [{ name: '$type_name', label: 'DataGerry object type name', type: 'text' }];
            definition.mapping = [{ target: 'title', sources: [{ field: '$type_name', origin: 'manual', confidence: 1 }], transform: { enabled, script } }];

            return definition;
        }


        it('seeds the script with the literal rather than with the response field', () => {
            const { payload } = compiler.compileForCreate(
                adjustedConstant("value = value + '_idoit';"),
                context()
            );

            expect(payload.connection.fieldBinding[0].enhancement.expertCode)
                .toBe('var value = "hardware";\nvalue = value + \'_idoit\';\nRESULT_VAR = value;');
        });


        it('borrows the first field the read operation returns as the binding origin', () => {
            const { payload } = compiler.compileForCreate(adjustedConstant('value = value.trim();'), context());
            const binding = payload.connection.fieldBinding[0];

            expect(binding.from[0]).toEqual({
                color: '#FFCFB5',
                field: 'body.$.result[i].id',
                type: 'response'
            });
            expect(binding.to[0]).toEqual({ color: '#C77E7E', field: 'body.$.title', type: 'request' });
        });


        it('points the target request body at the borrowed field, as every bound pair does', () => {
            const { payload } = compiler.compileForCreate(adjustedConstant('value = value.trim();'), context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.title)
                .toBe('#FFCFB5.(response).body.$.result[i].id');
        });


        it('keeps sending the plain literal while the adjustment is switched off', () => {
            const { payload } = compiler.compileForCreate(
                adjustedConstant("value = value + '_idoit';", false),
                context()
            );

            expect(payload.connection.fromConnector.methods[1].request.body.fields.title).toBe('hardware');
            expect(payload.connection.fieldBinding.length).toBe(0);
        });


        it('warns and falls back to the literal when the adjustment has no content', () => {
            const { payload, warnings } = compiler.compileForCreate(adjustedConstant('  '), context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.title).toBe('hardware');
            expect(payload.connection.fieldBinding.length).toBe(0);
            expect(warnings.some(warning => warning.includes('no content'))).toBeTrue();
        });


        it('still writes an unadjusted fixed value straight into the body', () => {
            const definition = incomingDefinition();
            definition.fields = [{ name: '$type_id', label: 'DataGerry object type ID', type: 'number' }];
            definition.mapping = [{ target: 'type_id', sources: [{ field: '$type_id', origin: 'manual', confidence: 1 }] }];

            const { payload } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.methods[1].request.body.fields.type_id).toBe('1');
            expect(payload.connection.fieldBinding.length).toBe(0);
        });
    });

    /* -------------------------------------------------- CONDITIONS ---------------------------------------------------- */

    /*
     * These used to compile to JavaScript - `.includes("srv")` and the like - written into the
     * loop's `condition`. OpenCelium's engine reads neither: it evaluates `expression`, in its own
     * language, and `condition` is a different shape it never looks at. So the restriction did
     * nothing at all, quietly, on every automation that used one.
     */
    describe('conditions', () => {
        function restricted(rules: any[], combinator: 'and' | 'or' = 'and', negate = false): AutomationDefinition {
            const definition = incomingDefinition();
            definition.conditions = { combinator, negate, rules };

            return definition;
        }


        it('restricts the loop with an `if` of its own rather than a property of the loop', () => {
            const { payload } = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'equals', value: 'srv01' }]), context()
            );
            const [loop, gate] = payload.connection.fromConnector.operators;

            expect(loop.type).toBe('loop');
            expect(loop.expression).toBe('for {%#FFCFB5.(response).body.$.result[*]%}');
            expect('condition' in loop).toBeFalse();

            expect(gate.type).toBe('if');
            expect(gate.index).toBe('1_0');
            expect(gate.expression).toBe('({%#FFCFB5.(response).body.$.result[i].title%} = "srv01")');
        });


        it('moves everything the loop does inside that `if`', () => {
            const plain = compiler.compileForCreate(incomingDefinition(), context()).payload;
            const gated = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'equals', value: 'x' }]), context()
            ).payload;

            expect(plain.connection.fromConnector.methods[1].index).toBe('1_0');
            expect(gated.connection.fromConnector.methods[1].index).toBe('1_0_0');
        });


        it('joins rules with the engine\'s own combinators', () => {
            const { payload } = compiler.compileForCreate(restricted([
                { field: 'title', operator: 'contains', value: 'srv' },
                { field: 'sysid', operator: 'is_not_empty', value: '' }
            ]), context());
            const gate = payload.connection.fromConnector.operators[1];

            expect(gate.expression).toContain(' && ');
            expect(gate.expression).toContain('Like "%srv%"');
            expect(gate.expression).toContain('NotNull');
        });


        /* Contains works on lists in the engine and throws on a string, so text uses Like. */
        it('maps a text comparison onto Like rather than Contains', () => {
            const { payload } = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'starts_with', value: 'SRV-' }]), context()
            );

            expect(payload.connection.fromConnector.operators[1].expression)
                .toBe('({%#FFCFB5.(response).body.$.result[i].title%} Like "SRV-%")');
        });


        /* A field can be empty by being absent or by holding "", and the engine separates them. */
        it('treats an absent value and an empty one as the same kind of empty', () => {
            const { payload } = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'is_empty', value: '' }]), context()
            );

            expect(payload.connection.fromConnector.operators[1].expression)
                .toBe('(({%#FFCFB5.(response).body.$.result[i].title%} IsNull) '
                    + '|| ({%#FFCFB5.(response).body.$.result[i].title%} = ""))');
        });


        it('negates the whole expression when the group is negated', () => {
            const { payload } = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'equals', value: 'x' }], 'or', true), context()
            );

            expect(payload.connection.fromConnector.operators[1].expression.startsWith('!(')).toBeTrue();
        });


        it('carries the rules into the node the editor draws', () => {
            const { payload } = compiler.compileForCreate(restricted([
                { field: 'title', operator: 'contains', value: 'srv' },
                { field: 'sysid', operator: 'is_not_empty', value: '' }
            ]), context());
            const gateNode = payload.connection.ui.workflowNodes
                .find(node => node.id === payload.connection.fromConnector.operators[1].id);

            expect(gateNode.data.conditionConfig.tree.items.length).toBe(2);
            expect(gateNode.data.conditionConfig.expression)
                .toBe(payload.connection.fromConnector.operators[1].expression);
        });


        it('leaves an unrestricted automation without a gate', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.operators.map(operator => operator.type))
                .toEqual(['loop']);
        });
    });

    /* --------------------------------------------------- LOOP NODE ---------------------------------------------------- */

    it('restates the loop on its node, with an untouched condition tree', () => {
        const { payload } = compiler.compileForCreate(incomingDefinition(), context());
        const loopNode = payload.connection.ui.workflowNodes[2];
        const loop = payload.connection.fromConnector.operators[0];

        expect(loopNode.id).toBe(loop.id);
        expect(loopNode.index).toBe(loop.index);
        expect(loopNode.data.conditionConfig.expression).toBe(loop.expression);
        expect(loopNode.data.conditionConfig.iterator).toBe('i');
        expect(loopNode.data.conditionConfig.tree)
            .toEqual({ id: '0-group', type: 'group', properties: { not: false }, items: [] });
    });
});
