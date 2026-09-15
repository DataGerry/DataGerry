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
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ReactiveFormsModule } from '@angular/forms';

import { of } from 'rxjs';

import { ConfigEditComponent } from './config-edit.component';
import { ExtendableOptionManagerService } from 'src/app/core/services/extendable-option-manager.service';
import { PortOptionType } from 'src/app/framework/models/port-option-type';

const PORT_STATUS_DESCRIPTOR = {
    optionType: PortOptionType.STATUS,
    manageLabel: 'Manage Statuses',
    modalTitle: 'Manage Port Statuses',
    itemLabel: 'Port Status',
    itemLabelPlural: 'Port Statuses'
};

/**
 * A locked field is opened for inspection, so nothing inside the editor may be editable - which the
 * fieldset enforces for every control, however it is bound. The manage action has to stay outside it.
 */
describe('ConfigEditComponent (read-only editor)', () => {
    let fixture: ComponentFixture<ConfigEditComponent>;
    let component: ConfigEditComponent;
    let optionManager: jasmine.SpyObj<ExtendableOptionManagerService>;

    /**
     * `type` deliberately matches no editor: the host renders the fieldset and the manage action on
     * its own, and creating a real editor would only drag its dependencies into this test.
     */
    function render(data: Record<string, unknown>, isReadOnly: boolean): void {
        component.data = { type: 'no-editor', ...data };
        component.isReadOnly = isReadOnly;
        fixture.detectChanges();
    }

    function fieldset(): HTMLFieldSetElement {
        return fixture.nativeElement.querySelector('fieldset');
    }

    beforeEach(async () => {
        optionManager = jasmine.createSpyObj<ExtendableOptionManagerService>('ExtendableOptionManagerService',
            ['descriptorOf', 'open']);
        optionManager.descriptorOf.and.callFake((optionType: string) =>
            optionType === PortOptionType.STATUS ? PORT_STATUS_DESCRIPTOR : null);
        optionManager.open.and.returnValue(of(undefined));

        await TestBed.configureTestingModule({
            imports: [ReactiveFormsModule],
            declarations: [ConfigEditComponent],
            providers: [{ provide: ExtendableOptionManagerService, useValue: optionManager }],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(ConfigEditComponent);
        component = fixture.componentInstance;
    });

    it('disables the whole editor through the fieldset when the field is read-only', () => {
        render({}, true);

        expect(fieldset().disabled).toBeTrue();
        expect(component.form.disabled).toBeTrue();
    });

    it('leaves the editor editable for a field that is not locked', () => {
        render({}, false);

        expect(fieldset().disabled).toBeFalse();
    });

    it('keeps the manage action outside the fieldset so it survives the lock', () => {
        render({ option_type: PortOptionType.STATUS }, true);

        const manageButton = fixture.nativeElement.querySelector('app-button');
        expect(manageButton).not.toBeNull();
        expect(fieldset().contains(manageButton)).toBeFalse();
    });

    it('offers no manage action for a select the user may not extend', () => {
        render({ option_type: 'CONTROL_MEASURE' }, false);

        expect(fixture.nativeElement.querySelector('app-button')).toBeNull();
    });
});
