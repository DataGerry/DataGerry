/**
 * Renders the real basic-step template together with the real app-form-select, so the
 * read-only special-type field is verified end to end: the reactive control is disabled in
 * code and the rendered dropdown has to follow it.
 */
import { CommonModule } from '@angular/common';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { FormsModule, ReactiveFormsModule } from '@angular/forms';
import { NgSelectModule } from '@ng-select/ng-select';
import { of } from 'rxjs';

import { TypeBasicStepComponent } from './type-basic-step.component';
import { SelectComponent } from 'src/app/core/components/base/select/select.component';
import { TypeService } from '../../../services/type.service';
import { SpecialTypeService } from '../../../services/special-type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { CmdbMode } from '../../../modes.enum';
import { CmdbType } from '../../../models/cmdb-type';
import { SpecialType } from '../../../models/special-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        public_id: 1,
        name: 'rack',
        label: 'Rack',
        description: '',
        active: true,
        fields: [],
        render_meta: {
            icon: 'fa fa-cube',
            sections: [],
            externals: [],
            summary: { fields: [] }
        },
        ...overrides
    } as CmdbType;
}

describe('TypeBasicStepComponent - rendered special type field', () => {
    let component: TypeBasicStepComponent;
    let fixture: ComponentFixture<TypeBasicStepComponent>;
    let specialTypeService: jasmine.SpyObj<SpecialTypeService>;

    const specialTypeSelect = (): HTMLElement | null =>
        fixture.nativeElement.querySelector('app-form-select ng-select');

    beforeEach(async () => {
        const typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypeByName']);
        typeService.getTypeByName.and.returnValue(of(null));

        specialTypeService = jasmine.createSpyObj<SpecialTypeService>('SpecialTypeService', [
            'getAvailableSpecialTypes', 'getAllSpecialTypes', 'getSchema', 'getCachedSchema'
        ]);
        specialTypeService.getAvailableSpecialTypes.and.returnValue(of({}));
        specialTypeService.getAllSpecialTypes.and.returnValue(of({ SUBNET: 'IPAM - Subnet class' }));
        specialTypeService.getCachedSchema.and.returnValue(null);

        const premiumFeatureService = jasmine.createSpyObj<PremiumFeatureService>('PremiumFeatureService', [
            'isAvailable$', 'promptUpgrade'
        ]);
        premiumFeatureService.isAvailable$.and.returnValue(of(true));

        await TestBed.configureTestingModule({
            declarations: [TypeBasicStepComponent, SelectComponent],
            imports: [CommonModule, FormsModule, ReactiveFormsModule, NgSelectModule],
            providers: [
                ValidationService,
                { provide: TypeService, useValue: typeService },
                { provide: SpecialTypeService, useValue: specialTypeService },
                { provide: ToastService, useValue: jasmine.createSpyObj<ToastService>('ToastService', ['error', 'success']) },
                { provide: LoaderService, useValue: jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']) },
                { provide: PremiumFeatureService, useValue: premiumFeatureService }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(TypeBasicStepComponent);
        component = fixture.componentInstance;
    });

    it('renders the assigned special type as a disabled dropdown in edit mode', async () => {
        component.mode = CmdbMode.Edit;
        component.TypeInstance = buildType({ name: 'subnet', label: 'Subnet', special_type: SpecialType.SUBNET });

        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();

        const select = specialTypeSelect();
        expect(select).not.toBeNull();
        expect(select.classList).toContain('ng-select-disabled');
        expect(select.querySelector<HTMLInputElement>('input').disabled).toBeTrue();
        expect(select.querySelector('.ng-value-label').textContent.trim()).toBe('SUBNET - IPAM - Subnet class');
    });

    it('explains that the assignment is fixed', async () => {
        component.mode = CmdbMode.Edit;
        component.TypeInstance = buildType({ special_type: SpecialType.SUBNET });

        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();

        expect(fixture.nativeElement.textContent).toContain('cannot be changed');
    });

    it('does not render a special type field for a regular type in edit mode', async () => {
        component.mode = CmdbMode.Edit;
        component.TypeInstance = buildType();

        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();

        expect(specialTypeSelect()).toBeNull();
    });

    it('keeps the dropdown editable in create mode', async () => {
        specialTypeService.getAvailableSpecialTypes.and.returnValue(of({ SUBNET: 'IPAM - Subnet class' }));
        component.mode = CmdbMode.Create;
        component.TypeInstance = buildType({ special_type: undefined });

        fixture.detectChanges();
        await fixture.whenStable();
        fixture.detectChanges();

        const select = specialTypeSelect();
        expect(select).not.toBeNull();
        expect(select.classList).not.toContain('ng-select-disabled');
        expect(component.specialType.disabled).toBeFalse();
    });
});
