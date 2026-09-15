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
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ReactiveFormsModule } from '@angular/forms';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { ArchwizardModule } from '@rg-software/angular-archwizard';

import { of } from 'rxjs';

import { CoreModule } from 'src/app/core/core.module';
import { ExtendableOptionCatalogService } from 'src/app/core/services/extendable-option-catalog.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CableOptionType } from 'src/app/framework/models/cable-option-type';
import { SpecialType } from 'src/app/framework/models/special-type';
import { ObjectService } from 'src/app/framework/services/object.service';
import { TypeService } from 'src/app/framework/services/type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';

import { CmdbPortConnection, PortConnectionPayload } from '../../models/port-connection.types';
import { ConnectionStep } from './connection-form';
import { CableManagementMode } from '../../models/port-connection.types';
import { CmdbPort, PortSide } from '../../models/ports-overview.types';
import { PortConnectionService } from '../../services/port-connection.service';
import { PortService } from '../../services/port.service';
import { CableCiPickerComponent } from '../cable-ci-picker/cable-ci-picker.component';
import { ChoiceCardGroupComponent } from '../choice-card-group/choice-card-group.component';
import { ConnectionEndpointPickerComponent } from '../connection-endpoint-picker/connection-endpoint-picker.component';
import { ObjectOptionPickerComponent } from '../object-option-picker/object-option-picker.component';
import { ConnectionFormModalComponent } from './connection-form-modal.component';
/* ------------------------------------------------------------------------------------------------------------------ */

/** The element the option panels are rendered on, so the scrolling modal body cannot clip them. */
const DROPDOWN_HOST = '.dg-modal-window';

const NEAR_PORT: CmdbPort = {
    public_id: 9940,
    object_id: 61,
    side: PortSide.SINGLE,
    name: 'Gi0/1',
    port_number: 1,
    status: null,
    port_type: null,
    speed: null,
    description: null,
    author_id: 1,
    creation_time: null,
    last_edit_time: null
};

/** A panel port of the device at the far end, so the face badge can be checked. */
const FAR_PORT: CmdbPort = {
    ...NEAR_PORT,
    public_id: 9942,
    object_id: 66,
    side: PortSide.FRONT,
    name: 'PP-01/F01'
};


describe('ConnectionFormModalComponent', () => {
    let fixture: ComponentFixture<ConnectionFormModalComponent>;
    let component: ConnectionFormModalComponent;
    let element: HTMLElement;

    let portService: jasmine.SpyObj<PortService>;
    let portConnectionService: jasmine.SpyObj<PortConnectionService>;
    let objectService: jasmine.SpyObj<ObjectService>;
    let typeService: jasmine.SpyObj<TypeService>;
    let activeModal: jasmine.SpyObj<NgbActiveModal>;
    let toast: jasmine.SpyObj<ToastService>;

    const sentPayload = (): PortConnectionPayload => portConnectionService.createConnection.calls.mostRecent().args[0];

    /** Reaches the wizard step the device and port have already been chosen on. */
    async function chooseFarEnd(): Promise<void> {
        const picker = fixture.debugElement.query(
            (node) => node.componentInstance instanceof ConnectionEndpointPickerComponent
        ).componentInstance as any;

        picker.onDeviceSelected({ public_id: 66, option_label: 'Switch #66' });
        fixture.detectChanges();
        await fixture.whenStable();

        picker.portControl.setValue(FAR_PORT.public_id);
        fixture.detectChanges();
        await fixture.whenStable();
    }

    async function goToNextStep(): Promise<void> {
        component.onNext();
        fixture.detectChanges();
        await fixture.whenStable();
    }

    beforeEach(async () => {
        // ng-select throws when appendTo matches nothing, so the modal window has to be on the page.
        document.body.insertAdjacentHTML('beforeend', '<div class="dg-modal-window"></div>');

        portService = jasmine.createSpyObj<PortService>('PortService', ['getPortsOfObject', 'getPort']);
        portConnectionService = jasmine.createSpyObj<PortConnectionService>(
            'PortConnectionService',
            ['getConnectionsOfObject', 'createConnection', 'updateCableInfo', 'getUnassignedCables']);
        objectService = jasmine.createSpyObj<ObjectService>('ObjectService', ['getObjects']);
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypes']);
        activeModal = jasmine.createSpyObj<NgbActiveModal>('NgbActiveModal', ['close', 'dismiss']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);

        const catalog = jasmine.createSpyObj<ExtendableOptionCatalogService>('Catalog', ['optionsForTypes']);
        const loader = jasmine.createSpyObj<LoaderService>(
            'LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        catalog.optionsForTypes.and.returnValue(of(new Map([
            [CableOptionType.CABLE_TYPE as string, [{ name: '9932', label: 'Cat5e' }]]
        ])));

        // The picker asks for port-capable types, the dialog for the Cable class - one spy, two answers.
        typeService.getTypes.and.callFake((params: any) => of({
            results: params?.filter?.special_type === SpecialType.CABLE
                ? [{ public_id: 30 }]
                : [{ public_id: 20 }],
            total: 1,
            count: 1
        }) as any);

        objectService.getObjects.and.returnValue(of({
            results: [{ object_information: { object_id: 66 }, summary_line: 'Switch #66' }],
            total: 1,
            count: 1
        }) as any);

        portService.getPortsOfObject.and.returnValue(of([FAR_PORT]));
        portService.getPort.and.returnValue(of(FAR_PORT));
        portConnectionService.getConnectionsOfObject.and.returnValue(of([]));
        portConnectionService.getUnassignedCables.and.returnValue(of({ results: [], total: 0, count: 0 } as any));
        portConnectionService.createConnection.and.returnValue(of({ public_id: 1 } as CmdbPortConnection));
        portConnectionService.updateCableInfo.and.returnValue(of({ public_id: 1 } as CmdbPortConnection));

        await TestBed.configureTestingModule({
            imports: [
                CoreModule,
                ReactiveFormsModule,
                ArchwizardModule,
                ChoiceCardGroupComponent,
                ConnectionEndpointPickerComponent,
                ObjectOptionPickerComponent,
                CableCiPickerComponent
            ],
            declarations: [ConnectionFormModalComponent],
            providers: [
                { provide: PortService, useValue: portService },
                { provide: PortConnectionService, useValue: portConnectionService },
                { provide: ObjectService, useValue: objectService },
                { provide: TypeService, useValue: typeService },
                { provide: ExtendableOptionCatalogService, useValue: catalog },
                { provide: LoaderService, useValue: loader },
                { provide: ToastService, useValue: toast },
                { provide: NgbActiveModal, useValue: activeModal }
            ]
        }).compileComponents();

        fixture = TestBed.createComponent(ConnectionFormModalComponent);
        component = fixture.componentInstance;
        element = fixture.nativeElement;
        component.port = NEAR_PORT;
        component.objectLabel = 'User #61';

        fixture.detectChanges();
        await fixture.whenStable();
    });

    afterEach(() => document.querySelector(DROPDOWN_HOST)?.remove());


    describe('the endpoints step', () => {
        it('opens on it, with the far end still unknown', () => {
            expect(component.currentStep).toBe(ConnectionStep.ENDPOINTS);
            expect(element.textContent).toContain('Gi0/1 - User #61');
            expect(element.textContent).not.toContain('Far end');
        });

        it('refuses to move on until a port is chosen, and says which answer is missing', async () => {
            await goToNextStep();

            expect(component.currentStep).toBe(ConnectionStep.ENDPOINTS);
            expect(element.textContent).toContain('Choose the port this cable runs to.');
        });

        it('names the chosen far end without repeating the object id', async () => {
            await chooseFarEnd();

            expect(component.farEndpoint.objectLabel).toBe('Switch #66');
            expect(element.textContent).not.toContain('#66 #66');
        });

        it('badges a panel port with its face, not with the option group it was listed under', async () => {
            await chooseFarEnd();

            expect(component.farEndpoint.sideLabel).toBe('Front');
        });

        it('opens its option panels off the scrolling body, so the dialog never scrolls to reveal one', () => {
            const selects = fixture.debugElement.queryAll((node) => node.name === 'ng-select');

            expect(selects.length).toBeGreaterThan(0);
            selects.forEach((select) => {
                // ng-select declares appendTo as a signal input, so the value has to be read out of it.
                const appendTo = select.componentInstance.appendTo;

                expect(typeof appendTo === 'function' ? appendTo() : appendTo).toBe(DROPDOWN_HOST);
            });
        });
    });


    describe('describing the cable here', () => {
        beforeEach(async () => {
            await chooseFarEnd();
            await goToNextStep();
        });

        it('asks how the cable is managed before asking about the cable itself', () => {
            expect(component.currentStep).toBe(ConnectionStep.MANAGEMENT);
        });

        it('reaches the cable step, which passes with nothing filled in', async () => {
            await goToNextStep();

            expect(component.currentStep).toBe(ConnectionStep.CABLE);

            await goToNextStep();

            expect(component.currentStep).toBe(ConnectionStep.REVIEW);
        });

        it('lists what will be written on the review step, leaving out what was not answered', async () => {
            await goToNextStep();
            component.form.patchValue({ cableName: 'patch 1-12', cableType: '9932', cableLength: '4' });
            fixture.detectChanges();
            await goToNextStep();

            const rows = component.reviewRows.map(row => `${ row.label }: ${ row.value }`);

            expect(rows).toContain('Cable name: patch 1-12');
            expect(rows).toContain('Cable type: Cat5e');
            expect(rows).toContain('Length: 4');
            expect(rows).toContain('Cable: Described here, not inventoried');
            expect(rows.some(row => row.startsWith('Color'))).toBeFalse();
        });

        it('writes the two ports, the length as text, and no cable CI key at all', async () => {
            await goToNextStep();
            component.form.patchValue({ cableName: 'patch 1-12', cableType: '9932', cableLength: '4' });
            fixture.detectChanges();
            await goToNextStep();

            component.onSubmit();

            expect(sentPayload()).toEqual({
                endpoints: [NEAR_PORT.public_id, FAR_PORT.public_id],
                connection_type: 'CABLE' as any,
                cable_name: 'patch 1-12',
                cable_type: 9932,
                cable_length: '4',
                cable_color: null,
                cable_description: null
            });
            expect(activeModal.close).toHaveBeenCalledWith(true);
        });
    });


    describe('linking an inventoried cable', () => {
        /** Reaches the management step and asks for the cable to be linked rather than described. */
        async function chooseCableCi(): Promise<void> {
            await chooseFarEnd();
            await goToNextStep();

            component.onSelectManagementMode(CableManagementMode.CABLE_CI);
            fixture.detectChanges();
            await fixture.whenStable();
        }

        it('holds the step back until a cable is picked', async () => {
            await chooseCableCi();

            await goToNextStep();

            expect(component.currentStep).toBe(ConnectionStep.MANAGEMENT);
            expect(element.textContent).toContain('Choose the cable to link');
        });

        it('never asks for the cable fields - the linked object already carries them', async () => {
            await chooseCableCi();
            component.form.patchValue({ cableCiId: 67 });
            fixture.detectChanges();

            expect(component.connectionForm.activeSteps()).not.toContain(ConnectionStep.CABLE);

            await goToNextStep();

            expect(component.currentStep).toBe(ConnectionStep.REVIEW);
            expect(element.querySelector('[formcontrolname="cableName"]')).toBeNull();
        });

        it('reviews the cable by name and says where its details come from', async () => {
            await chooseCableCi();
            component.form.patchValue({ cableCiId: 67 });
            fixture.detectChanges();
            await goToNextStep();

            const rows = component.reviewRows.map(row => `${ row.label }: ${ row.value }`);

            expect(rows).toContain('Cable details: Taken from the linked cable');
            expect(rows.some(row => row.startsWith('Cable name'))).toBeFalse();
            expect(rows.some(row => row.startsWith('Length'))).toBeFalse();
        });

        it('sends the reference alone, so the server takes the values from the cable', async () => {
            await chooseCableCi();
            component.form.patchValue({ cableCiId: 67 });
            fixture.detectChanges();
            await goToNextStep();

            component.onSubmit();

            expect(sentPayload()).toEqual({
                endpoints: [NEAR_PORT.public_id, FAR_PORT.public_id],
                connection_type: 'CABLE' as any,
                cable_ci_id: 67
            });
        });
    });


    describe('editing an internal pairing', () => {
        beforeEach(async () => {
            component.connection = {
                public_id: 5,
                endpoints: [NEAR_PORT.public_id, FAR_PORT.public_id],
                connection_type: 'INTERNAL' as any,
                cable: null,
                author_id: 1,
                creation_time: null,
                last_edit_time: null
            };

            component.ngOnInit();
            fixture.detectChanges();
            await fixture.whenStable();
        });

        it('reads as read-only and offers no wizard at all', () => {
            expect(component.isInternal).toBeTrue();
            expect(element.querySelector('.connection-wizard')).toBeNull();
            expect(element.textContent).toContain('Created automatically:');
        });

        it('still names both ends, so the user sees what is paired', () => {
            expect(component.farEndpoint.portName).toBe('PP-01/F01');
        });

        it('writes nothing even if a submit is forced', () => {
            component.onSubmit();

            expect(portConnectionService.createConnection).not.toHaveBeenCalled();
            expect(portConnectionService.updateCableInfo).not.toHaveBeenCalled();
        });
    });
});
