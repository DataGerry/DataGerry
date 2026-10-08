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
import { fakeAsync, flushMicrotasks, TestBed } from '@angular/core/testing';
import { NgbModal } from '@ng-bootstrap/ng-bootstrap';
import { SimpleChange } from '@angular/core';
import { of, throwError } from 'rxjs';

import { AutomationRunPanelComponent } from './automation-run-panel.component';
import { AutomationsService } from '../../services/automations.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { SaveBeforeRunChoice } from '../save-before-run-modal/save-before-run-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

const STORAGE_KEY = 'automations.run.alwaysSaveBeforeRun';

describe('AutomationRunPanelComponent - saving before a run', () => {
    let automations: jasmine.SpyObj<AutomationsService>;
    let modal: jasmine.SpyObj<NgbModal>;
    let saveChanges: jasmine.Spy;
    let order: string[];

    /** The dialog answers with `choice`, or is closed without one when it is null. */
    function answering(choice: SaveBeforeRunChoice | null): { componentInstance: any } {
        const ref = {
            componentInstance: {} as any,
            result: choice ? Promise.resolve(choice) : Promise.reject('dismissed')
        };
        modal.open.and.returnValue(ref as any);

        return ref;
    }


    function panel(unsaved: boolean, canSave = true): AutomationRunPanelComponent {
        const component = TestBed.runInInjectionContext(() => new AutomationRunPanelComponent());
        component.schedulerId = 173;
        component.unsavedChanges = unsaved;
        component.canSaveChanges = canSave;
        component.saveChanges = saveChanges;

        return component;
    }


    beforeEach(() => {
        window.localStorage.removeItem(STORAGE_KEY);
        order = [];

        automations = jasmine.createSpyObj<AutomationsService>(
            'AutomationsService',
            ['executeScheduler', 'getRunningSchedulers', 'getScheduler', 'getSchedulerLogs']
        );
        automations.getRunningSchedulers.and.returnValue(of([]));
        automations.getScheduler.and.returnValue(of({ lastExecution: { success: { duration: 40000 } } }));
        automations.getSchedulerLogs.and.returnValue(of([]));
        automations.executeScheduler.and.callFake(() => {
            order.push('run');

            return of({}) as any;
        });
        modal = jasmine.createSpyObj<NgbModal>('NgbModal', ['open']);
        saveChanges = jasmine.createSpy('saveChanges').and.callFake(() => {
            order.push('save');

            return of(undefined);
        });

        TestBed.configureTestingModule({
            providers: [
                { provide: AutomationsService, useValue: automations },
                { provide: NgbModal, useValue: modal },
                { provide: ToastService, useValue: jasmine.createSpyObj('ToastService', ['success', 'error']) }
            ]
        });
    });


    afterEach(() => {
        window.localStorage.removeItem(STORAGE_KEY);
    });


    it('runs straight away when nothing is unsaved', () => {
        const component = panel(false);

        component.start();

        expect(modal.open).not.toHaveBeenCalled();
        expect(order).toEqual(['run']);
        component.ngOnDestroy();
    });


    it('asks before running over unsaved changes, and saves first when told to', fakeAsync(() => {
        answering({ action: 'save', remember: false });
        const component = panel(true);

        component.start();
        flushMicrotasks();

        expect(modal.open).toHaveBeenCalled();
        expect(order).toEqual(['save', 'run']);
        expect(window.localStorage.getItem(STORAGE_KEY)).toBeNull();
        component.ngOnDestroy();
    }));


    it('runs the saved version without saving when that is chosen', fakeAsync(() => {
        answering({ action: 'run-saved', remember: false });
        const component = panel(true);

        component.start();
        flushMicrotasks();

        expect(order).toEqual(['run']);
        component.ngOnDestroy();
    }));


    it('does nothing when the dialog is closed', fakeAsync(() => {
        answering(null);
        const component = panel(true);

        component.start();
        flushMicrotasks();

        expect(order).toEqual([]);
    }));


    it('stops asking once "always" was chosen, and asks again when that is undone', fakeAsync(() => {
        answering({ action: 'save', remember: true });
        const first = panel(true);
        first.start();
        flushMicrotasks();
        first.ngOnDestroy();

        expect(window.localStorage.getItem(STORAGE_KEY)).toBe('true');

        modal.open.calls.reset();
        order = [];
        const second = panel(true);
        second.start();
        flushMicrotasks();
        second.ngOnDestroy();

        expect(modal.open).not.toHaveBeenCalled();
        expect(order).toEqual(['save', 'run']);

        second.askAgain();
        answering(null);
        const third = panel(true);
        third.start();
        flushMicrotasks();

        expect(modal.open).toHaveBeenCalled();
    }));


    it('still asks when the changes cannot be saved, even with "always" set', fakeAsync(() => {
        window.localStorage.setItem(STORAGE_KEY, 'true');
        const ref = answering({ action: 'run-saved', remember: false });
        const component = panel(true, false);

        component.start();
        flushMicrotasks();

        expect(ref.componentInstance.canSave).toBeFalse();
        expect(saveChanges).not.toHaveBeenCalled();
        expect(order).toEqual(['run']);
        component.ngOnDestroy();
    }));


    it('does not run the old version when saving fails', fakeAsync(() => {
        answering({ action: 'save', remember: false });
        saveChanges.and.returnValue(throwError(() => ({ error: { message: 'nope' } })));
        const component = panel(true);

        component.start();
        flushMicrotasks();

        expect(automations.executeScheduler).not.toHaveBeenCalled();
        expect(component.starting).toBeFalse();
    }));


    describe('following a run', () => {

        it('measures the progress against the last run, and never shows it finished early', () => {
            const component = panel(false);
            component.expectedMs = 40000;

            component.elapsedMs = 10000;
            expect(component.progress).toBe(25);
            expect(component.progressText).toBe('10 s of about 40 s');

            component.elapsedMs = 90000;
            expect(component.progress).toBe(95);
            expect(component.progressText).toBe('1 min 30 s - longer than the last run (40 s)');
        });


        it('still moves without a previous run, short of full', () => {
            const component = panel(false);
            component.expectedMs = null;
            component.elapsedMs = 600000;

            expect(component.progress).toBeGreaterThan(90);
            expect(component.progress).toBeLessThanOrEqual(95);
            expect(component.progressText).toBe('10 min so far');
        });


        it('reads the expected length and picks up a run already going when it opens', () => {
            automations.getRunningSchedulers.and.returnValue(of([{ schedulerId: 173 }]));
            const component = panel(false);

            component.ngOnChanges({ schedulerId: new SimpleChange(null, 173, true) });

            expect(component.expectedMs).toBe(40000);
            expect(component.running).toBeTrue();
            component.ngOnDestroy();
        });


        /* OpenCelium may answer the start only when the run ends, and the request gives up first. */
        it('counts a start that timed out as started when the run is going', () => {
            automations.executeScheduler.and.returnValue(throwError(() => ({ error: { message: 'timeout' } })));
            automations.getRunningSchedulers.and.returnValue(of([{ schedulerId: 173, avgDuration: 5000 }]));
            const component = panel(false);
            component.expectedMs = null;

            component.start();

            expect(component.running).toBeTrue();
            expect(component.expectedMs).toBe(5000);
            component.ngOnDestroy();
        });
    });
});
