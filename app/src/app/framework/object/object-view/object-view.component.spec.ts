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
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, convertToParamMap } from '@angular/router';
import { Subject, of, throwError } from 'rxjs';

import { LoaderService } from 'src/app/core/services/loader.service';
import { RenderResult } from '../../models/cmdb-render';
import { ObjectChangeNotifierService } from '../../services/object-change-notifier.service';
import { ObjectService } from '../../services/object.service';
import { TypeService } from '../../services/type.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { PermissionService } from 'src/app/modules/auth/services/permission.service';
import { ObjectViewComponent } from './object-view.component';

/* ------------------------------------------------------------------------------------------------------------------ */

const OBJECT_ID = 42;
const NOTES = 'dg-rack-notes';

const renderResultWith = (notes: string): RenderResult => ({
    object_information: { object_id: OBJECT_ID },
    fields: [{ name: NOTES, value: notes }]
} as RenderResult);

const permissionServiceWith = (granted: boolean) => ({
    hasRight: () => granted,
    hasExtendedRight: () => granted
});

/* ------------------------------------------------------------------------------------------------------------------ */

describe('ObjectViewComponent (re-read after a write)', () => {
    let fixture: ComponentFixture<ObjectViewComponent>;
    let component: ObjectViewComponent;

    let objectService: jasmine.SpyObj<ObjectService>;
    let toastService: jasmine.SpyObj<ToastService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let objectChanges: ObjectChangeNotifierService;

    const notes = () => component.renderResult?.fields[0].value;

    beforeEach(async () => {
        objectService = jasmine.createSpyObj('ObjectService', ['getObject']);
        toastService = jasmine.createSpyObj('ToastService', ['success', 'error']);
        loaderService = jasmine.createSpyObj('LoaderService', ['show', 'hide']);
        (loaderService as any).isLoading$ = of(false);

        objectService.getObject.and.returnValue(of(renderResultWith('note as saved')));

        await TestBed.configureTestingModule({
            declarations: [ObjectViewComponent],
            providers: [
                { provide: ObjectService, useValue: objectService },
                { provide: ToastService, useValue: toastService },
                { provide: LoaderService, useValue: loaderService },
                { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
                { provide: PremiumFeatureService, useValue: { isAvailable: () => true } },
                { provide: PermissionService, useValue: permissionServiceWith(true) },
                {
                    provide: TypeService,
                    useValue: { getTypes: () => of({ results: [] }) }
                },
                {
                    provide: ActivatedRoute,
                    useValue: {
                        data: of({ object: renderResultWith('note as resolved') }),
                        queryParamMap: of(convertToParamMap({}))
                    }
                }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(ObjectViewComponent);
        component = fixture.componentInstance;
        objectChanges = TestBed.inject(ObjectChangeNotifierService);
        // The template is not rendered: these tests drive the object stream, not the markup.
        component.ngOnInit();
    });

    it('starts from the object the route resolved', () => {
        expect(notes()).toBe('note as resolved');
        expect(objectService.getObject).not.toHaveBeenCalled();
    });

    it('reads the object again when it was written, and rebuilds the view from the answer', () => {
        objectChanges.notifyChanged(OBJECT_ID);

        expect(objectService.getObject).toHaveBeenCalledWith(OBJECT_ID);
        expect(notes()).toBe('note as saved');
    });

    it('ignores a write announced for another object', () => {
        objectChanges.notifyChanged(OBJECT_ID + 1);

        expect(objectService.getObject).not.toHaveBeenCalled();
        expect(notes()).toBe('note as resolved');
    });

    it('raises and releases the loader around the re-read', () => {
        objectChanges.notifyChanged(OBJECT_ID);

        expect(loaderService.show).toHaveBeenCalledTimes(1);
        expect(loaderService.hide).toHaveBeenCalledTimes(1);
    });

    it('reports a failed re-read and keeps listening for the next write', () => {
        objectService.getObject.and.returnValue(throwError(() => ({ error: { message: 'boom' } })));
        objectChanges.notifyChanged(OBJECT_ID);

        expect(toastService.error).toHaveBeenCalledWith('boom');
        expect(notes()).toBe('note as resolved');

        objectService.getObject.and.returnValue(of(renderResultWith('note as saved')));
        objectChanges.notifyChanged(OBJECT_ID);

        expect(notes()).toBe('note as saved');
    });

    it('keeps the object on screen when the re-read comes back empty', () => {
        objectService.getObject.and.returnValue(of(null));
        objectChanges.notifyChanged(OBJECT_ID);

        expect(notes()).toBe('note as resolved');
    });

    it('leaves the loader balanced when a second write cancels the re-read in flight', () => {
        const firstRead = new Subject<RenderResult>();
        const secondRead = new Subject<RenderResult>();
        objectService.getObject.and.returnValues(firstRead, secondRead);

        objectChanges.notifyChanged(OBJECT_ID);
        objectChanges.notifyChanged(OBJECT_ID);
        secondRead.next(renderResultWith('note as saved'));
        secondRead.complete();

        expect(loaderService.show).toHaveBeenCalledTimes(2);
        expect(loaderService.hide).toHaveBeenCalledTimes(2);
        expect(notes()).toBe('note as saved');
    });

    it('stops listening once the view is gone', () => {
        component.ngOnDestroy();
        objectChanges.notifyChanged(OBJECT_ID);

        expect(objectService.getObject).not.toHaveBeenCalled();
    });
});

/* ------------------------------------------------------------------------------------------------------------------ */

describe('ObjectViewComponent (the graph view answers to the CI Explorer right)', () => {

    const buildView = async (queryParams: Record<string, string>, granted: boolean) => {
        await TestBed.configureTestingModule({
            declarations: [ObjectViewComponent],
            providers: [
                { provide: ObjectService, useValue: { getObject: () => of(renderResultWith('note')) } },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['success', 'error']) },
                { provide: LoaderService, useValue: { show: () => { }, hide: () => { }, isLoading$: of(false) } },
                { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
                { provide: PremiumFeatureService, useValue: { isAvailable: () => true } },
                { provide: PermissionService, useValue: permissionServiceWith(granted) },
                { provide: TypeService, useValue: { getTypes: () => of({ results: [] }) } },
                {
                    provide: ActivatedRoute,
                    useValue: {
                        data: of({ object: renderResultWith('note') }),
                        queryParamMap: of(convertToParamMap(queryParams))
                    }
                }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        const view = TestBed.createComponent(ObjectViewComponent).componentInstance;
        view.ngOnInit();

        return view;
    };

    it('opens the graph for ?view=graph when the right is granted', async () => {
        expect((await buildView({ view: 'graph' }, true)).isGraphView).toBeTrue();
    });

    it('keeps the table on screen for ?view=graph when the right is missing', async () => {
        expect((await buildView({ view: 'graph' }, false)).isGraphView).toBeFalse();
    });

    it('refuses the toggle when the right is missing', async () => {
        const view = await buildView({}, false);

        view.toggleView(true);

        expect(view.isGraphView).toBeFalse();
    });
});
