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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/
import { Subject, of } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { RelationService } from 'src/app/framework/services/relaion.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { FullscreenModalService } from 'src/app/core/services/fullscreen-modal.service';
import { ApiCallService } from 'src/app/services/api-call.service';

import { FilterProfile } from '../interfaces/graph.interfaces';
import { GraphProfileService } from './graph-profile.service';

describe('GraphProfileService', () => {
    let service: GraphProfileService;
    let loader: jasmine.SpyObj<LoaderService>;

    beforeEach(() => {
        const api = jasmine.createSpyObj<ApiCallService>('ApiCallService', ['callGet']);
        const fullscreen = jasmine.createSpyObj<FullscreenModalService>('FullscreenModalService', ['open']);
        loader = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']);

        service = new GraphProfileService(api, fullscreen);
    });

    describe('loadFilterOptions', () => {
        function services(types: any, relations: any) {
            return {
                typeService: { getTypes: () => types } as unknown as TypeService,
                relationService: { getRelations: () => relations } as unknown as RelationService
            };
        }

        it('asks for the types and the relations at the same time', () => {
            const types = new Subject<any>();
            const relations = new Subject<any>();
            const { typeService, relationService } = services(types, relations);

            service.loadFilterOptions(typeService, relationService, loader).subscribe();

            // Serialised loading would leave the relations request unsubscribed until types answered.
            expect(types.observed).toBeTrue();
            expect(relations.observed).toBeTrue();
        });

        it('builds an option per entry and hides the loader when both answer', () => {
            const { typeService, relationService } = services(
                of({ results: [{ public_id: 1, label: 'Server' }] }),
                of([{ public_id: 9, relation_name: 'runs-on' }])
            );
            let result: { types: any[]; relations: any[] } | undefined;

            service.loadFilterOptions(typeService, relationService, loader).subscribe(r => result = r);

            expect(result!.types).toEqual([{ public_id: 1, display_name: 'Server' }]);
            expect(result!.relations).toEqual([{ public_id: 9, display_name: 'runs-on' }]);
            expect(loader.hide).toHaveBeenCalled();
        });

        it('falls back to the id when an entry has no label', () => {
            const { typeService, relationService } = services(of([{ public_id: 4 }]), of([]));
            let result: { types: any[] } | undefined;

            service.loadFilterOptions(typeService, relationService, loader).subscribe(r => result = r);

            expect(result!.types).toEqual([{ public_id: 4, display_name: '#4' }]);
        });

        it('treats a missing list as empty', () => {
            const { typeService, relationService } = services(of(null), of(undefined));
            let result: { types: any[]; relations: any[] } | undefined;

            service.loadFilterOptions(typeService, relationService, loader).subscribe(r => result = r);

            expect(result!.types).toEqual([]);
            expect(result!.relations).toEqual([]);
        });
    });

    describe('applyProfile', () => {
        const profiles = [
            { public_id: 7, name: 'Network', types_filter: [1, 2], relations_filter: [3] }
        ] as FilterProfile[];

        it('returns the filters of the chosen profile', () => {
            expect(service.applyProfile(profiles, 7, [], [])).toEqual({
                typesFilter: [1, 2],
                relationsFilter: [3]
            });
        });

        it('keeps the current filters when no profile matches', () => {
            expect(service.applyProfile(profiles, 99, [5], [6])).toEqual({
                typesFilter: [5],
                relationsFilter: [6]
            });
        });

        it('treats a profile without filters as empty', () => {
            const bare = [{ public_id: 8, name: 'Bare' }] as FilterProfile[];

            expect(service.applyProfile(bare, 8, [5], [6])).toEqual({
                typesFilter: [],
                relationsFilter: []
            });
        });
    });
});
