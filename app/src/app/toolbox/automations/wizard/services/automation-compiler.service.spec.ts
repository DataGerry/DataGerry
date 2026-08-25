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
    AutomationDefinition,
    AUTOMATION_DERIVED_CALLS_VERSION,
    createEmptyAutomationDefinition
} from '../models/automation-definition.model';
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
    // These suites are about the calls the compiler derives, which only an automation from before
    // the sequence step still asks for. A fresh definition lists its calls instead - see the
    // 'sequence-defined automations' suite below.
    definition.version = AUTOMATION_DERIVED_CALLS_VERSION;
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
                .some(error => error.includes('No field is sent anywhere yet'))).toBeTrue();
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

    /* ------------------------------------------------- ADDED CALLS ---------------------------------------------------- */

    /*
     * The skeleton is derived and cannot grow, which is the point of it. A system that needs more
     * than the skeleton - i-doit writes an object's data into categories of its own - gets it here.
     */
    describe('added calls', () => {
        /* Outgoing, so the added call and the step it follows are both on the foreign system. */
        function withExtra(extra: Partial<AutomationDefinition['extras'][number]> = {}): AutomationDefinition {
            const definition = incomingDefinition();
            definition.direction = 'outgoing';
            definition.fields = [{ name: 'hostname', label: 'Hostname', type: 'text' }];
            definition.mapping = [
                { target: 'params.title', sources: [{ field: 'hostname', origin: 'manual', confidence: 1 }] }
            ];
            definition.extras = [{
                id: 'extra-1',
                after: '1_0',
                kind: 'operation',
                operation: 'cmdb.object.update',
                ...extra
            }];

            return definition;
        }


        it('runs beside the step it follows, not inside it', () => {
            const { payload } = compiler.compileForCreate(withExtra(), context());
            const added = payload.connection.fromConnector.methods
                .find(method => method.name === 'cmdb.object.update');

            expect(added?.index).toBe('1_1');
        });


        /*
         * A request value carrying a reference used to be written into the body and left there;
         * every capture pairs one with a binding, so without it the reference is only text.
         */
        it('wires a reference somebody put into one of its values', () => {
            const anchorColor = compiler.compileForCreate(withExtra(), context())
                .payload.connection.fromConnector.methods[1].color;
            const reference = `${anchorColor}.(response).body.$.result.id`;

            const { payload } = compiler.compileForCreate(
                withExtra({ body: { 'params.id': reference } }),
                context()
            );
            const added = payload.connection.fromConnector.methods
                .find(method => method.name === 'cmdb.object.update');
            const binding = payload.connection.fieldBinding
                .find(entry => entry.to[0].field === 'body.$.params.id');

            expect(added?.request.body.fields.params.id).toBe(reference);
            expect(binding?.from[0]).toEqual({
                color: anchorColor,
                field: 'body.$.result.id',
                type: 'response'
            });
        });


        /* Checked against the added call's own colour: the same path on another call is bound by
           the field assignment, and finding that one would prove nothing. */
        it('leaves a value that is only text unwired', () => {
            const { payload } = compiler.compileForCreate(
                withExtra({ body: { 'params.title': 'by hand' } }),
                context()
            );
            const added = payload.connection.fromConnector.methods
                .find(method => method.name === 'cmdb.object.update')!;

            expect(payload.connection.fieldBinding.some(entry =>
                entry.to[0].color === added.color && entry.to[0].field === 'body.$.params.title'))
                .toBeFalse();
        });


        it('carries the values entered for it', () => {
            const { payload } = compiler.compileForCreate(
                withExtra({ body: { 'params.title': 'by hand' } }),
                context()
            );
            const added = payload.connection.fromConnector.methods
                .find(method => method.name === 'cmdb.object.update');

            expect(added?.request.body.fields.params.title).toBe('by hand');
        });


        /*
         * A condition of the user's own, in the grammar the editor writes: the tested value in
         * braces, a literal in quotes, and a right-hand side that is itself a reference left as one.
         */
        it('places a condition in the sequence and runs what follows inside it', () => {
            const definition = withExtra({
                id: 'extra-if',
                kind: 'if',
                operation: '',
                condition: {
                    left: '#FFCFB5.(response).body.$.results[i].type_id',
                    operator: 'Like',
                    right: 'srv%'
                }
            });

            definition.extras = [...definition.extras, {
                id: 'extra-inside',
                // Named by the entry it follows, not by the position that entry landed on.
                after: 'extra-if',
                kind: 'operation',
                operation: 'cmdb.object.update'
            }];

            const { payload } = compiler.compileForCreate(definition, context());
            const gate = payload.connection.fromConnector.operators.find(entry => entry.id === 'if-extra-if');
            const inside = payload.connection.fromConnector.methods
                .find(method => method.id === 'method-extra-inside');

            expect(gate.index).toBe('1_1');
            expect(gate.iterator).toBeNull();
            expect(gate.expression)
                .toBe("({%#FFCFB5.(response).body.$.results[i].type_id%} Like 'srv%')");

            // Inside the condition, not beside it.
            expect(inside.index).toBe('1_1_0');
        });


        /*
         * Two conditions placed after the same step are siblings: the execution tree runs them one
         * after the other, and the editor has to draw them that way too. Hanging both off the step
         * they were placed after drew two arrows out of it - a fork, which is neither what was
         * built nor what runs, and what an automation with two conditions came out looking like.
         */
        it('draws a second condition after the first one, not beside it', () => {
            const definition = withExtra({
                id: 'extra-if',
                kind: 'if',
                operation: '',
                condition: { left: '#C77E7E.(response).body.$.result[*]', operator: 'IsEmpty', right: '' }
            });

            definition.extras = [...definition.extras, {
                id: 'extra-second-if',
                // Placed after the same step as the first condition, which is what makes them
                // siblings rather than one inside the other.
                after: '1_0',
                kind: 'if',
                operation: '',
                condition: { left: '#C77E7E.(response).body.$.result[*]', operator: 'NotEmpty', right: '' }
            }];

            const { payload } = compiler.compileForCreate(definition, context());
            const operators = payload.connection.fromConnector.operators;
            const first = operators.find(entry => entry.id === 'if-extra-if');
            const second = operators.find(entry => entry.id === 'if-extra-second-if');
            const edges = payload.connection.ui.workflowEdges;

            // Beside each other in the tree, so they run one after the other.
            expect(first.index).toBe('1_1');
            expect(second.index).toBe('1_2');

            // And drawn as a chain: the second is reached down the first one's miss.
            expect(edges.find(edge => edge.target === second.id)).toEqual(jasmine.objectContaining({
                source: first.id,
                sourceHandle: 'false',
                targetHandle: 'left'
            }));

            // One arrow out of the step both were placed after, not two.
            const anchorId = payload.connection.fromConnector.methods
                .find(method => method.index === '1_0').id;

            expect(edges.filter(edge => edge.source === anchorId).length).toBe(1);
        });


        /* A loop passes on out of its right exit once it has run out, as the captures draw it. */
        it('draws a call after a loop as following it', () => {
            const definition = withExtra({
                id: 'extra-loop',
                kind: 'loop',
                operation: '',
                loop: { list: '#C77E7E.(response).body.$.result.interfaces[*]', iterator: 'j' }
            });

            definition.extras = [...definition.extras, {
                id: 'extra-after-loop',
                after: '1_0',
                kind: 'operation',
                operation: 'cmdb.object.update'
            }];

            const { payload } = compiler.compileForCreate(definition, context());
            const loop = payload.connection.fromConnector.operators.find(entry => entry.id === 'loop-extra-loop');
            const after = payload.connection.fromConnector.methods
                .find(method => method.id === 'method-extra-after-loop');
            const edges = payload.connection.ui.workflowEdges;

            expect(loop.index).toBe('1_1');
            expect(after.index).toBe('1_2');
            expect(edges.find(edge => edge.target === after.id)).toEqual(jasmine.objectContaining({
                source: loop.id,
                sourceHandle: 'right',
                targetHandle: 'left'
            }));
        });


        it('leaves the right-hand side a reference when it is one', () => {
            const definition = withExtra({
                id: 'extra-if',
                kind: 'if',
                operation: '',
                condition: {
                    left: '#FFCFB5.(response).body.$.results[i].type_id',
                    operator: '=',
                    right: '#C77E7E.(response).body.$.result.id'
                }
            });

            const { payload } = compiler.compileForCreate(definition, context());
            const gate = payload.connection.fromConnector.operators.find(entry => entry.type === 'if');

            expect(gate.expression).toBe(
                '({%#FFCFB5.(response).body.$.results[i].type_id%} '
                + '= {%#C77E7E.(response).body.$.result.id%})'
            );
        });


        it('drops the right-hand side where the comparison has none', () => {
            const definition = withExtra({
                id: 'extra-if',
                kind: 'if',
                operation: '',
                condition: {
                    left: '#FFCFB5.(response).body.$.results[i].type_id',
                    operator: 'NotNull',
                    right: ''
                }
            });

            const { payload } = compiler.compileForCreate(definition, context());
            const gate = payload.connection.fromConnector.operators.find(entry => entry.type === 'if');
            const node = payload.connection.ui.workflowNodes.find(entry => entry.id === gate.id);

            expect(gate.expression)
                .toBe('({%#FFCFB5.(response).body.$.results[i].type_id%} NotNull)');
            expect(node.type).toBe('if');
            expect(node.data.conditionConfig.tree.items[0].properties.operator).toBe('NotNull');
            expect('rightField' in node.data.conditionConfig.tree.items[0].properties).toBeFalse();
        });


        /* An operator with no expression is rejected outright, so it is reported instead. */
        it('reports a condition that tests nothing', () => {
            const definition = withExtra({
                id: 'extra-if',
                kind: 'if',
                operation: '',
                condition: { left: '', operator: '=', right: 'x' }
            });

            const { payload, warnings } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.operators.some(entry => entry.id === 'if-extra-if'))
                .toBeFalse();
            expect(warnings.some(warning => warning.includes('nothing to test'))).toBeTrue();
        });


        /*
         * A loop of the user's own, over a list some earlier answer holds. Its entries get a name
         * of their own - 'i' belongs to the loop over the objects being synchronised.
         */
        it('walks a list of its own and runs what follows once per entry', () => {
            const definition = withExtra({
                id: 'extra-loop',
                kind: 'loop',
                operation: '',
                loop: { list: '#C77E7E.(response).body.$.result.interfaces[*]', iterator: 'j' }
            });

            definition.extras = [...definition.extras, {
                id: 'extra-inside',
                after: 'extra-loop',
                kind: 'operation',
                operation: 'cmdb.object.update'
            }];

            const { payload } = compiler.compileForCreate(definition, context());
            const loop = payload.connection.fromConnector.operators
                .find(entry => entry.id === 'loop-extra-loop');
            const inside = payload.connection.fromConnector.methods
                .find(method => method.id === 'method-extra-inside');

            expect(loop.type).toBe('loop');
            expect(loop.index).toBe('1_1');
            expect(loop.iterator).toBe('j');
            expect(loop.expression).toBe('for {%#C77E7E.(response).body.$.result.interfaces[*]%}');

            expect(inside.index).toBe('1_1_0');
        });


        /* The editor rebuilds a loop's expression from its rule tree, so the tree has to hold one. */
        it('gives every loop the rule the editor draws it from', () => {
            const definition = withExtra({
                id: 'extra-loop',
                kind: 'loop',
                operation: '',
                loop: { list: '#C77E7E.(response).body.$.result.interfaces[*]', iterator: 'j' }
            });

            const { payload } = compiler.compileForCreate(definition, context());
            const nodes = payload.connection.ui.workflowNodes.filter(node => node.type === 'loop');

            for (const node of nodes) {
                const rule = node.data.conditionConfig.tree.items[0];

                expect(rule.properties.operator).toBe('for');
                expect(rule.properties.leftField).toContain('[*]');
                expect(node.data.conditionConfig.expression).toContain(rule.properties.leftField);
            }

            // The one every automation has, and the one that was added.
            expect(nodes.length).toBe(2);
        });


        it('reports a loop that walks nothing', () => {
            const definition = withExtra({
                id: 'extra-loop',
                kind: 'loop',
                operation: '',
                loop: { list: '', iterator: 'j' }
            });

            const { payload, warnings } = compiler.compileForCreate(definition, context());

            expect(payload.connection.fromConnector.operators.some(entry => entry.id === 'loop-extra-loop'))
                .toBeFalse();
            expect(warnings.some(warning => warning.includes('names no list'))).toBeTrue();
        });


        /* Removing a branch can leave one behind; saying so beats compiling it somewhere else. */
        it('reports a call whose step is gone', () => {
            const { warnings } = compiler.compileForCreate(withExtra({ after: '9_9' }), context());

            expect(warnings.some(warning => warning.includes('no longer exists'))).toBeTrue();
        });


        /*
         * For an endpoint no invoker describes. It carries no response schema, which is the trade
         * the wizard states where it offers one.
         */
        it('writes a free request out in full, with no connector behind it', () => {
            const definition = withExtra({
                kind: 'http',
                operation: '',
                verb: 'PUT',
                endpoint: 'https://monitor.example/api/hosts',
                headers: { Authorization: 'Bearer x' }
            });

            const { payload } = compiler.compileForCreate(definition, context());
            const added = payload.connection.fromConnector.methods
                .find(method => method.methodType === 'HTTP_REQUEST');

            expect(added?.request.method).toBe('PUT');
            expect(added?.request.endpoint).toBe('https://monitor.example/api/hosts');
            expect(added?.request.header.Authorization).toBe('Bearer x');
            // Named after the verb and belonging to no connector, as the capture shows.
            expect(added?.name).toBe('PUT');
            expect(added?.connector).toBeNull();
            expect(added?.response.fail.status).toBe('500');
        });


        /*
         * A free request describes nothing, so everything it sends is typed in - and a value typed
         * in may be a reference, which is how such a call reaches what ran before it.
         */
        it('sends the headers and the body a free request was given', () => {
            const definition = withExtra({
                kind: 'http',
                operation: '',
                verb: 'POST',
                endpoint: 'https://monitor.example/api/hosts',
                headers: { 'Content-Type': 'application/json' },
                body: {
                    'host.name': '#C77E7E.(response).body.$.result.id',
                    'host.source': 'DataGerry'
                }
            });

            const { payload } = compiler.compileForCreate(definition, context());
            const added = payload.connection.fromConnector.methods
                .find(method => method.methodType === 'HTTP_REQUEST');

            expect(added?.request.header['Content-Type']).toBe('application/json');
            expect(added?.request.body.fields.host.name).toBe('#C77E7E.(response).body.$.result.id');
            expect(added?.request.body.fields.host.source).toBe('DataGerry');
        });


        /* A free request is its own kind of node in the editor, not a connector node without one. */
        it('draws it as a system node rather than a connector node', () => {
            const definition = withExtra({ kind: 'http', operation: '', endpoint: 'https://x' });

            const { payload } = compiler.compileForCreate(definition, context());
            const node = payload.connection.ui.workflowNodes.find(item => item.type === 'system');

            expect(node?.id).toContain('system-');
            expect(node?.data.kind).toBe('system');
            expect(node?.data.title).toBe('HTTP Request');
            expect('connector' in node!.data).toBeFalse();
        });


        it('reports an operation the system does not have', () => {
            const { warnings } = compiler.compileForCreate(
                withExtra({ operation: 'cmdb.nonsense' }),
                context()
            );

            expect(warnings.some(warning => warning.includes('offers no operation'))).toBeTrue();
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
            expect(gate.expression).toBe("({%#FFCFB5.(response).body.$.result[i].title%} = 'srv01')");
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
            expect(gate.expression).toContain("Like '%srv%'");
            expect(gate.expression).toContain('NotNull');
        });


        /* Contains works on lists in the engine and throws on a string, so text uses Like. */
        it('maps a text comparison onto Like rather than Contains', () => {
            const { payload } = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'starts_with', value: 'SRV-' }]), context()
            );

            expect(payload.connection.fromConnector.operators[1].expression)
                .toBe("({%#FFCFB5.(response).body.$.result[i].title%} Like 'SRV-%')");
        });


        /* A field can be empty by being absent or by holding "", and the engine separates them. */
        it('treats an absent value and an empty one as the same kind of empty', () => {
            const { payload } = compiler.compileForCreate(
                restricted([{ field: 'title', operator: 'is_empty', value: '' }]), context()
            );

            expect(payload.connection.fromConnector.operators[1].expression)
                .toBe("(({%#FFCFB5.(response).body.$.result[i].title%} IsNull "
                    + "|| {%#FFCFB5.(response).body.$.result[i].title%} = ''))");
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

            const tree = gateNode.data.conditionConfig.tree;

            expect(tree.items.length).toBe(2);
            expect(gateNode.data.conditionConfig.expression)
                .toBe(payload.connection.fromConnector.operators[1].expression);

            // The editor regenerates the expression from this tree, so it has to say the same
            // thing: the resolved reference rather than the field name, the engine's own operator,
            // the joiner on the group, and no right-hand side where there is nothing to compare to.
            expect(tree.properties.conjunction).toBe('&&');
            expect(tree.items[0].properties.leftField)
                .toBe('#FFCFB5.(response).body.$.result[i].title');
            expect(tree.items[0].properties.operator).toBe('Like');
            expect(tree.items[0].properties.rightField).toBe('%srv%');
            expect(tree.items[1].properties.operator).toBe('NotNull');
            expect('rightField' in tree.items[1].properties).toBeFalse();
        });


        it('leaves an unrestricted automation without a gate', () => {
            const { payload } = compiler.compileForCreate(incomingDefinition(), context());

            expect(payload.connection.fromConnector.operators.map(operator => operator.type))
                .toEqual(['loop']);
        });
    });

    /* --------------------------------------------------- LOOP NODE ---------------------------------------------------- */

    /*
     * The tree is the form the editor draws the loop in and rebuilds its expression from, so it
     * carries the `for` rule rather than nothing. The two oldest captures leave it empty; the later
     * capture of a connection holding a loop and three conditions carries the rule, and an empty
     * tree would come back from the editor walking nothing.
     */
    it('restates the loop on its node, as the rule the editor draws it from', () => {
        const { payload } = compiler.compileForCreate(incomingDefinition(), context());
        const loopNode = payload.connection.ui.workflowNodes[2];
        const loop = payload.connection.fromConnector.operators[0];

        expect(loopNode.id).toBe(loop.id);
        expect(loopNode.index).toBe(loop.index);
        expect(loopNode.data.conditionConfig.expression).toBe(loop.expression);
        expect(loopNode.data.conditionConfig.iterator).toBe('i');
        expect(loopNode.data.conditionConfig.tree).toEqual({
            id: `${loop.id}-group`,
            type: 'group',
            properties: { not: false },
            items: [{
                id: `${loop.id}-rule`,
                type: 'rule',
                properties: { operator: 'for', leftField: '#FFCFB5.(response).body.$.result[*]' }
            }]
        });
    });
});


/*
 * Since the sequence step, what the target system is asked to do is listed there rather than worked
 * out from an action. The action was a guess at what a given system calls creating something, and
 * it was wrong often enough that it stopped being asked for.
 */
describe('AutomationCompilerService sequence-defined automations', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });


    /**
     * Written since the change, and reading DataGerry - so nothing at all is derived beyond the
     * read. The other direction does still get one call, but from the mapping rather than from an
     * action; that is the 'writing into DataGerry' suite.
     */
    function sequenceDefined(): AutomationDefinition {
        const definition = incomingDefinition();
        definition.version = 2;
        definition.direction = 'outgoing';

        return definition;
    }


    it('reads the source and stops there when the sequence lists nothing', () => {
        const { payload } = compiler.compileForCreate(sequenceDefined(), context());

        expect(payload.connection.fromConnector.methods.map(method => method.name))
            .toEqual(['GetObjects']);
    });


    it('still walks the source collection, which is the automation itself', () => {
        const { payload } = compiler.compileForCreate(sequenceDefined(), context());

        expect(payload.connection.fromConnector.operators.map(operator => operator.type))
            .toEqual(['loop']);
    });


    /* An action nobody chose must not hold back an automation that never needed one. */
    it('accepts a definition whose action the target system cannot perform', () => {
        const definition = sequenceDefined();
        definition.target.operation = 'delete';

        expect(compiler.validate(definition, context())).toEqual([]);
    });


    it('keeps deriving the calls of an automation written before the change', () => {
        const { payload } = compiler.compileForCreate(incomingDefinition(), context());

        expect(payload.connection.fromConnector.methods.length).toBeGreaterThan(1);
    });
});


/*
 * The sequence is built on top of a compiled connection, so anything that withholds the connection
 * withholds the screen that would fix it. These two pull in opposite directions on purpose.
 */
describe('AutomationCompilerService what blocks what', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });


    function withoutMapping(): AutomationDefinition {
        const definition = incomingDefinition();
        definition.version = 2;
        definition.mapping = [];

        return definition;
    }


    it('compiles an automation that sends nothing yet', () => {
        expect(compiler.structuralErrors(withoutMapping(), context())).toEqual([]);
    });


    /* Which is what the sequence step needs: a container to hang the first call inside. */
    it('gives that automation a container to add a call to', () => {
        const { payload } = compiler.compileForCreate(withoutMapping(), context());

        expect(payload.connection.fromConnector.operators.some(operator => operator.type === 'loop'))
            .toBeTrue();
    });


    it('still refuses to call it finished', () => {
        expect(compiler.validate(withoutMapping(), context()))
            .toContain(jasmine.stringContaining('No field is sent anywhere yet'));
    });


    it('reports a missing object type as structural, because nothing can be read without one', () => {
        const definition = withoutMapping();
        definition.objectType = { typeId: null, name: '', label: '' };

        expect(compiler.structuralErrors(definition, context()).length).toBeGreaterThan(0);
    });
});


/*
 * An automation that writes into DataGerry gets that call from the compiler, not from the
 * sequence: the sequence configures the other system, and this one is what the automation is for.
 * What it writes is the mapping, which for this direction is filled in on the fields step.
 */
describe('AutomationCompilerService writing into DataGerry', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });


    const answer = '#FFCFB5.(response).body.$.result[i].title';


    function collecting(...mapping: AutomationDefinition['mapping']): AutomationDefinition {
        const definition = incomingDefinition();
        definition.version = 2;
        definition.mapping = mapping;

        return definition;
    }


    function fromAnswer(target: string, reference = answer): AutomationDefinition['mapping'][number] {
        return { target, sources: [{ field: '', origin: 'manual', confidence: 1, reference }] };
    }


    function typedIn(target: string, literal: string): AutomationDefinition['mapping'][number] {
        return { target, sources: [{ field: '', origin: 'manual', confidence: 1, literal }] };
    }


    it('adds the call that creates the object', () => {
        const { payload } = compiler.compileForCreate(collecting(fromAnswer('hostname')), context());

        expect(payload.connection.fromConnector.methods.map(method => method.name))
            .toEqual(['cmdb.objects.read', 'AddObject']);
    });


    it('writes the chosen object type, which nothing is read from', () => {
        const { payload } = compiler.compileForCreate(collecting(fromAnswer('hostname')), context());
        const write = payload.connection.fromConnector.methods[1];

        expect(write.request.body.fields.type_id).toBe('1');
    });


    /* DataGerry takes an object's fields as name/value pairs, not as keys of the body. */
    it('writes each mapped field as a name and a value', () => {
        const { payload } = compiler.compileForCreate(
            collecting(fromAnswer('hostname'), typedIn('location', 'Rack 4')),
            context()
        );

        expect(payload.connection.fromConnector.methods[1].request.body.fields.fields).toEqual([
            { name: 'hostname', value: answer },
            { name: 'location', value: 'Rack 4' }
        ]);
    });


    it('wires a value that came from an earlier answer', () => {
        const { payload } = compiler.compileForCreate(collecting(fromAnswer('hostname')), context());
        const [binding] = payload.connection.fieldBinding;

        expect(binding.from[0]).toEqual({
            color: '#FFCFB5',
            field: 'body.$.result[i].title',
            type: 'response'
        });
        expect(binding.to[0].field).toBe('body.$.fields[0].value');
    });


    /* A typed-in value already stands in the body; a binding would give it an origin it has not got. */
    it('leaves a typed-in value unbound', () => {
        const { payload } = compiler.compileForCreate(collecting(typedIn('location', 'Rack 4')), context());

        expect(payload.connection.fieldBinding).toEqual([]);
    });


    it('runs the write once per object, inside the loop', () => {
        const { payload } = compiler.compileForCreate(collecting(fromAnswer('hostname')), context());
        const loop = payload.connection.fromConnector.operators.find(operator => operator.type === 'loop');

        expect(payload.connection.fromConnector.methods[1].index.startsWith(`${loop!.index}_`)).toBeTrue();
    });


    it('writes nothing at all while nothing is mapped', () => {
        const { payload } = compiler.compileForCreate(collecting(), context());

        expect(payload.connection.fromConnector.methods.map(method => method.name))
            .toEqual(['cmdb.objects.read']);
    });


    /* The other direction sends its values the other way; this call has no business there. */
    it('adds no such call to an automation that reads DataGerry', () => {
        const definition = collecting(fromAnswer('hostname'));
        definition.direction = 'outgoing';

        const { payload } = compiler.compileForCreate(definition, context());

        expect(payload.connection.fromConnector.methods.some(method => method.name === 'AddObject'))
            .toBeFalse();
    });
});


/*
 * The link step asks which fields to transfer only where they are what gets read. Writing into
 * DataGerry it says so - "the mapping chooses the fields" - and never fills them in, so requiring
 * them left an automation that could be built, could not be saved, and had no screen that would
 * have fixed it.
 */
describe('AutomationCompilerService fields the link step does not ask for', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });


    function writingDataGerry(): AutomationDefinition {
        const definition = incomingDefinition();
        definition.version = 2;
        definition.fields = [];
        definition.mapping = [{
            target: 'hostname',
            sources: [{
                field: '',
                origin: 'manual',
                confidence: 1,
                reference: '#FFCFB5.(response).body.$.result[i].title'
            }]
        }];

        return definition;
    }


    it('lets an automation that writes DataGerry be saved without them', () => {
        expect(compiler.validate(writingDataGerry(), context())).toEqual([]);
    });


    it('still asks for them where they are what gets read', () => {
        const definition = writingDataGerry();
        definition.direction = 'outgoing';

        expect(compiler.validate(definition, context()))
            .toContain(jasmine.stringContaining('at least one field to transfer'));
    });


    it('compiles the write even so, because the mapping is what it needs', () => {
        const { payload } = compiler.compileForCreate(writingDataGerry(), context());

        expect(payload.connection.fromConnector.methods.map(method => method.name))
            .toEqual(['cmdb.objects.read', 'AddObject']);
    });
});


/*
 * A request body is not a flat set of keys. DataGerry takes an object's fields as a list, so a path
 * has to be able to name a position in one - and an operation offers everything its interface
 * accepts, which is rarely all an automation wants to send.
 */
describe('AutomationCompilerService request values', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });


    function corrected(body: Record<string, string | null>): AutomationDefinition {
        const definition = incomingDefinition();
        definition.overrides = { '1_0': { body } };

        return definition;
    }


    function targetBody(definition: AutomationDefinition): any {
        const { payload } = compiler.compileForCreate(definition, context());

        return payload.connection.fromConnector.methods
            .find(method => method.index === '1_0')!.request.body.fields;
    }


    it('writes into a position of a list, not into a key that looks like one', () => {
        const body = targetBody(corrected({ 'fields[0].name': 'hostname' }));

        expect(body.fields).toEqual([{ name: 'hostname' }]);
    });


    it('fills the list up to the position asked for', () => {
        const body = targetBody(corrected({ 'fields[1].name': 'serial' }));

        expect(body.fields.length).toBe(2);
        expect(body.fields[1]).toEqual({ name: 'serial' });
    });


    /* An empty key is not the same as an absent one to every API, so removing has to mean absent. */
    it('takes a value the operation offers out of the request', () => {
        const body = targetBody(corrected({ version: null }));

        expect('version' in body).toBeFalse();
    });


    it('leaves everything else where it is', () => {
        const body = targetBody(corrected({ version: null }));

        expect('type_id' in body).toBeTrue();
    });


    it('takes a header out the same way', () => {
        const definition = incomingDefinition();
        definition.overrides = { '1_0': { headers: { Authorization: null } } };

        const { payload } = compiler.compileForCreate(definition, context());
        const write = payload.connection.fromConnector.methods.find(method => method.index === '1_0');

        expect('Authorization' in write!.request.header).toBeFalse();
    });
});


/*
 * Which field ends up where is a reference in a request value, so an adjustment for it cannot hang
 * on a mapping entry - there is none. It is keyed by the call and the path instead, because two
 * calls can write the same path and an adjustment belongs to exactly one of them.
 */
describe('AutomationCompilerService adjusting what the sequence writes', () => {
    let compiler: AutomationCompilerService;

    beforeEach(() => {
        compiler = new AutomationCompilerService(new TargetCatalogService());
    });


    const reference = '#FFCFB5.(response).body.$.results[i].fields[0].value';


    function adjustedAt(key: string, script: string): AutomationDefinition {
        const definition = incomingDefinition();
        definition.overrides = { '1_0': { body: { 'params.title': reference } } };
        definition.adjustments = { [key]: { enabled: true, script } };

        return definition;
    }


    function enhancementFor(definition: AutomationDefinition): string {
        const { payload } = compiler.compileForCreate(definition, context());

        return payload.connection.fieldBinding
            .find(entry => entry.to[0].field === 'body.$.params.title')!
            .enhancement.expertCode;
    }


    it('runs the script on the value the call was given', () => {
        expect(enhancementFor(adjustedAt('1_0:params.title', "value = value + '!';")))
            .toBe("var value = VAR_0;\nvalue = value + '!';\nRESULT_VAR = value;");
    });


    /* Keyed by the call as well: the same path on another call is a different value. */
    it('leaves the value alone when the adjustment names another call', () => {
        expect(enhancementFor(adjustedAt('9_9:params.title', "value = value + '!';")))
            .toBe('RESULT_VAR = VAR_0;');
    });


    it('leaves it alone while the adjustment is switched off', () => {
        const definition = adjustedAt('1_0:params.title', "value = value + '!';");
        definition.adjustments['1_0:params.title'].enabled = false;

        expect(enhancementFor(definition)).toBe('RESULT_VAR = VAR_0;');
    });
});
