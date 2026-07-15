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
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { ActivatedRoute, Router } from '@angular/router';
import { Location } from '@angular/common';
import { of, throwError } from 'rxjs';

import { ObjectEditComponent } from './object-edit.component';
import { ObjectService } from '../../services/object.service';
import { TypeService } from '../../services/type.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { LocationService } from '../../services/location.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbObject, MultiDataSectionEntry } from '../../models/cmdb-object';

/* ------------------------------------------------------------------------------------------------------------------ */

describe('ObjectEditComponent (PATCH flow)', () => {
    let component: ObjectEditComponent;
    let fixture: ComponentFixture<ObjectEditComponent>;

    let objectService: jasmine.SpyObj<ObjectService>;
    let toastService: jasmine.SpyObj<ToastService>;
    let locationService: jasmine.SpyObj<LocationService>;
    let sidebarService: jasmine.SpyObj<SidebarService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let router: jasmine.SpyObj<Router>;

    const OBJECT_ID = 42;
    const TYPE_ID = 7;

    /** Seeds the component with a pristine snapshot and a fresh edit form. */
    const seed = (snapshot: Partial<CmdbObject>, form: UntypedFormGroup) => {
        component.objectInstance = { public_id: OBJECT_ID, type_id: TYPE_ID } as CmdbObject;
        (component as any).originalSnapshot = { fields: [], multi_data_sections: [], ...snapshot };
        component.renderForm = form;
        component.activeState = true;
    };

    beforeEach(async () => {
        objectService = jasmine.createSpyObj('ObjectService', ['getObject', 'patchObject', 'changeState']);
        toastService = jasmine.createSpyObj('ToastService', ['success', 'error']);
        locationService = jasmine.createSpyObj('LocationService', ['deleteLocationForObject']);
        sidebarService = jasmine.createSpyObj('SidebarService', ['ReloadSideBarData']);
        loaderService = jasmine.createSpyObj('LoaderService', ['show', 'hide']);
        (loaderService as any).isLoading$ = of(false);
        router = jasmine.createSpyObj('Router', ['navigate']);

        objectService.getObject.and.returnValue(of(null));
        objectService.patchObject.and.returnValue(of({ result: {} }));
        objectService.changeState.and.returnValue(of(true));
        locationService.deleteLocationForObject.and.returnValue(of(null));

        await TestBed.configureTestingModule({
            declarations: [ObjectEditComponent],
            providers: [
                { provide: ObjectService, useValue: objectService },
                { provide: TypeService, useValue: jasmine.createSpyObj('TypeService', ['getType']) },
                { provide: ToastService, useValue: toastService },
                { provide: LocationService, useValue: locationService },
                { provide: SidebarService, useValue: sidebarService },
                { provide: LoaderService, useValue: loaderService },
                { provide: Router, useValue: router },
                { provide: Location, useValue: jasmine.createSpyObj('Location', ['back']) },
                { provide: ActivatedRoute, useValue: { params: of({ publicID: OBJECT_ID }) } }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(ObjectEditComponent);
        component = fixture.componentInstance;
        // Intentionally skip detectChanges()/ngOnInit — these tests drive editObject() directly
        // with a hand-built form and snapshot, isolating the PATCH orchestration.
    });

    /* ---------------------------------------------------- EVENTS ------------------------------------------------- */

    it('does nothing when the form is invalid', () => {
        const form = new UntypedFormGroup({
            hostname: new UntypedFormControl('', Validators.required)
        });
        seed({ fields: [{ name: 'hostname', value: 'old' }] }, form);

        component.editObject();

        expect(objectService.patchObject).not.toHaveBeenCalled();
        expect(objectService.changeState).not.toHaveBeenCalled();
    });

    it('skips PATCH but still persists state when nothing on the object changed', () => {
        const form = new UntypedFormGroup({
            hostname: new UntypedFormControl('same')
        });
        seed({ fields: [{ name: 'hostname', value: 'same' }] }, form);

        component.editObject();

        expect(objectService.patchObject).not.toHaveBeenCalled();
        expect(objectService.changeState).toHaveBeenCalledWith(OBJECT_ID, true);
        expect(sidebarService.ReloadSideBarData).toHaveBeenCalled();
        expect(toastService.success).toHaveBeenCalled();
        expect(router.navigate).toHaveBeenCalledWith(['/framework/object/view/' + OBJECT_ID]);
    });

    it('sends only the changed field and then persists state on success', () => {
        const form = new UntypedFormGroup({
            hostname: new UntypedFormControl('new-host'),
            os: new UntypedFormControl('linux')
        });
        seed({ fields: [{ name: 'hostname', value: 'old-host' }, { name: 'os', value: 'linux' }] }, form);

        component.editObject();

        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            fields: [{ name: 'hostname', value: 'new-host' }]
        });
        expect(objectService.changeState).toHaveBeenCalledWith(OBJECT_ID, true);
        expect(router.navigate).toHaveBeenCalledWith(['/framework/object/view/' + OBJECT_ID]);
    });

    it('attaches the commit comment to the payload when there is a real change', () => {
        const form = new UntypedFormGroup({ hostname: new UntypedFormControl('new-host') });
        seed({ fields: [{ name: 'hostname', value: 'old-host' }] }, form);
        component.commitForm = new UntypedFormGroup({ comment: new UntypedFormControl('changed hostname') });

        component.editObject();

        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            fields: [{ name: 'hostname', value: 'new-host' }],
            comment: 'changed hostname'
        });
    });

    it('builds created / edited / deleted MDS rows from the section control', () => {
        const editedSection: MultiDataSectionEntry = {
            section_id: 'net',
            highest_id: 3,
            values: [
                { multi_data_id: 1, data: [{ name: 'ip', value: '10.0.0.5' }] }, // edited
                { multi_data_id: 2, data: [{ name: 'ip', value: '10.0.0.9' }] }  // created
            ]
        };
        const form = new UntypedFormGroup({
            'dg-mds-net': new UntypedFormControl(editedSection)
        });
        seed({
            multi_data_sections: [{
                section_id: 'net',
                highest_id: 2,
                values: [
                    { multi_data_id: 1, data: [{ name: 'ip', value: '10.0.0.1' }] },
                    { multi_data_id: 9, data: [{ name: 'ip', value: '10.0.0.99' }] } // will be deleted
                ]
            }]
        }, form);

        component.editObject();

        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            created_mds_rows: [{ section_id: 'net', data: [{ name: 'ip', value: '10.0.0.9' }] }],
            edited_mds_rows: [{ section_id: 'net', multi_data_id: 1, data: [{ name: 'ip', value: '10.0.0.5' }] }],
            deleted_mds_rows: [{ section_id: 'net', multi_data_id: 9 }]
        });
    });

    it('shows an error toast and routes to the type list when the PATCH fails', () => {
        objectService.patchObject.and.returnValue(throwError(() => ({ error: { message: 'boom' } })));
        const form = new UntypedFormGroup({ hostname: new UntypedFormControl('new-host') });
        seed({ fields: [{ name: 'hostname', value: 'old-host' }] }, form);

        component.editObject();

        expect(toastService.error).toHaveBeenCalledWith('boom');
        expect(objectService.changeState).not.toHaveBeenCalled();
        expect(router.navigate).toHaveBeenCalledWith(['/framework/object/type/' + TYPE_ID]);
    });

    it('sends dg_location as a field and attaches location_name when the location changes', () => {
        const form = new UntypedFormGroup({
            dg_location: new UntypedFormControl(8),
            locationTreeName: new UntypedFormControl('Rack 14 / Server A'),
            hostname: new UntypedFormControl('new-host')
        });
        seed({ fields: [{ name: 'hostname', value: 'old-host' }, { name: 'dg_location', value: 1 }] }, form);

        component.editObject();

        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            fields: [{ name: 'dg_location', value: 8 }, { name: 'hostname', value: 'new-host' }],
            location_name: 'Rack 14 / Server A'
        });
    });

    it('still patches with the location label when only the location name changed', () => {
        const form = new UntypedFormGroup({
            dg_location: new UntypedFormControl(5),
            locationTreeName: new UntypedFormControl('Renamed location'),
            hostname: new UntypedFormControl('same')
        });
        seed({ fields: [{ name: 'hostname', value: 'same' }, { name: 'dg_location', value: 5 }] }, form);

        component.editObject();

        // dg_location is unchanged so the diff drops it, but a location-only edit must still
        // reach the backend, so it is forced back in together with the new label.
        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            fields: [{ name: 'dg_location', value: 5 }],
            location_name: 'Renamed location'
        });
    });

    it('never attaches a location when the object has none selected', () => {
        const form = new UntypedFormGroup({
            dg_location: new UntypedFormControl(0),
            hostname: new UntypedFormControl('new-host')
        });
        seed({ fields: [{ name: 'hostname', value: 'old-host' }, { name: 'dg_location', value: 0 }] }, form);

        component.editObject();

        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            fields: [{ name: 'hostname', value: 'new-host' }]
        });
    });

    it('deletes the location via the dedicated route and keeps dg_location out of the patch', () => {
        const form = new UntypedFormGroup({
            dg_location: new UntypedFormControl(0),
            locationForObjectExists: new UntypedFormControl('true'),
            hostname: new UntypedFormControl('new-host')
        });
        seed({ fields: [{ name: 'hostname', value: 'old-host' }, { name: 'dg_location', value: 5 }] }, form);

        component.editObject();

        expect(locationService.deleteLocationForObject).toHaveBeenCalledWith(OBJECT_ID);
        // dg_location must not ride along in the patch when the removal is handled separately.
        expect(objectService.patchObject).toHaveBeenCalledWith(OBJECT_ID, {
            fields: [{ name: 'hostname', value: 'new-host' }]
        });
    });

    it('skips the patch but still deletes the location when only the location was removed', () => {
        const form = new UntypedFormGroup({
            dg_location: new UntypedFormControl(0),
            locationForObjectExists: new UntypedFormControl('true'),
            hostname: new UntypedFormControl('same')
        });
        seed({ fields: [{ name: 'hostname', value: 'same' }, { name: 'dg_location', value: 5 }] }, form);

        component.editObject();

        expect(locationService.deleteLocationForObject).toHaveBeenCalledWith(OBJECT_ID);
        expect(objectService.patchObject).not.toHaveBeenCalled();
        expect(objectService.changeState).toHaveBeenCalledWith(OBJECT_ID, true);
    });
});
