import { ComponentFixture, TestBed } from '@angular/core/testing';
import { of, throwError } from 'rxjs';

import { TypeBasicStepComponent } from './type-basic-step.component';
import { TypeService } from '../../../services/type.service';
import { SpecialTypeService } from '../../../services/special-type.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { PremiumFeatureService } from 'src/app/settings/license-management/premium-feature/premium-feature.service';
import { LicenseFeature } from 'src/app/settings/license-management/models/license.model';
import { CmdbMode } from '../../../modes.enum';
import { CmdbType } from '../../../models/cmdb-type';
import { SpecialType } from '../../../models/special-type';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        public_id: 1,
        name: 'server',
        label: 'Server',
        description: 'A server type',
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

describe('TypeBasicStepComponent (type creation - basic information)', () => {
    let component: TypeBasicStepComponent;
    let fixture: ComponentFixture<TypeBasicStepComponent>;

    let typeService: jasmine.SpyObj<TypeService>;
    let specialTypeService: jasmine.SpyObj<SpecialTypeService>;
    let toastService: jasmine.SpyObj<ToastService>;
    let loaderService: jasmine.SpyObj<LoaderService>;
    let premiumFeatureService: jasmine.SpyObj<PremiumFeatureService>;

    beforeEach(async () => {
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypeByName']);
        typeService.getTypeByName.and.returnValue(of(null));

        specialTypeService = jasmine.createSpyObj<SpecialTypeService>('SpecialTypeService', [
            'getAvailableSpecialTypes', 'getAllSpecialTypes', 'getSchema', 'getCachedSchema'
        ]);
        specialTypeService.getAvailableSpecialTypes.and.returnValue(of({}));
        specialTypeService.getAllSpecialTypes.and.returnValue(of({}));
        specialTypeService.getCachedSchema.and.returnValue(null);

        toastService = jasmine.createSpyObj<ToastService>('ToastService', ['error', 'success']);
        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide']);

        premiumFeatureService = jasmine.createSpyObj<PremiumFeatureService>('PremiumFeatureService', [
            'isAvailable$', 'promptUpgrade'
        ]);
        premiumFeatureService.isAvailable$.and.returnValue(of(false));

        await TestBed.configureTestingModule({
            declarations: [TypeBasicStepComponent],
            providers: [
                ValidationService,
                { provide: TypeService, useValue: typeService },
                { provide: SpecialTypeService, useValue: specialTypeService },
                { provide: ToastService, useValue: toastService },
                { provide: LoaderService, useValue: loaderService },
                { provide: PremiumFeatureService, useValue: premiumFeatureService }
            ]
        })
            .overrideComponent(TypeBasicStepComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeBasicStepComponent);
        component = fixture.componentInstance;
    });

    describe('form defaults', () => {
        it('creates the expected controls with sensible defaults', () => {
            expect(component.form.contains('name')).toBeTrue();
            expect(component.form.contains('label')).toBeTrue();
            expect(component.form.contains('special_type')).toBeTrue();
            expect(component.form.contains('description')).toBeTrue();
            expect(component.form.contains('active')).toBeTrue();
            expect(component.form.contains('icon')).toBeTrue();
            expect(component.form.contains('ci_explorer_color')).toBeTrue();

            expect(component.form.get('active').value).toBeTrue();
            expect(component.icon.value).toBe('fa fa-cube');
            expect(component.form.get('ci_explorer_color').value).toBe('#8896a5');
        });

        it('makes name and label required', () => {
            component.name.setValue('');
            component.label.setValue('');
            expect(component.name.hasError('required')).toBeTrue();
            expect(component.label.hasError('required')).toBeTrue();
        });
    });

    describe('name character validation', () => {
        it('flags names with invalid characters', () => {
            component.name.setValue('web server');
            expect(component.name.hasError('invalidCharacters')).toBeTrue();
        });

        it('accepts a valid alphanumeric name', () => {
            component.name.setValue('web_server-1');
            expect(component.name.hasError('invalidCharacters')).toBeFalse();
        });
    });

    describe('assign()', () => {
        it('copies form values onto the type instance in create mode (including special type)', () => {
            component.mode = CmdbMode.Create;
            component.typeInstance = buildType();

            component.assign({
                name: 'router',
                label: 'Router',
                description: 'edge router',
                active: false,
                special_type: SpecialType.SUBNET,
                icon: 'fa fa-network-wired',
                ci_explorer_color: '#123456'
            });

            expect(component.typeInstance.name).toBe('router');
            expect(component.typeInstance.label).toBe('Router');
            expect(component.typeInstance.description).toBe('edge router');
            expect(component.typeInstance.active).toBeFalse();
            expect(component.typeInstance.special_type).toBe(SpecialType.SUBNET);
            expect(component.typeInstance.render_meta.icon).toBe('fa fa-network-wired');
            expect(component.typeInstance.ci_explorer_color).toBe('#123456');
        });

        it('does not touch special_type in edit mode', () => {
            component.mode = CmdbMode.Edit;
            component.typeInstance = buildType({ special_type: SpecialType.VLAN });

            component.assign({
                name: 'router',
                label: 'Router',
                description: '',
                active: true,
                special_type: SpecialType.SUBNET,
                icon: 'fa fa-cube',
                ci_explorer_color: '#123456'
            });

            expect(component.typeInstance.special_type).toBe(SpecialType.VLAN);
        });
    });

    describe('setRandomColor()', () => {
        it('produces a valid 6-digit hex color', () => {
            component.setRandomColor();
            expect(component.form.get('ci_explorer_color').value).toMatch(/^#[0-9a-f]{6}$/);
        });
    });

    describe('normalizeSpecialTypeValue()', () => {
        it('normalizes empty / non-string values to null and trims real values', () => {
            const normalize = (v: unknown) => (component as any).normalizeSpecialTypeValue(v);
            expect(normalize(null)).toBeNull();
            expect(normalize(undefined)).toBeNull();
            expect(normalize('')).toBeNull();
            expect(normalize('   ')).toBeNull();
            expect(normalize(123)).toBeNull();
            expect(normalize('SUBNET')).toBe('SUBNET');
            expect(normalize('  VLAN  ')).toBe('VLAN');
        });
    });

    describe('create mode initialization', () => {
        beforeEach(() => {
            component.mode = CmdbMode.Create;
            component.typeInstance = buildType({ ci_explorer_color: '#abcabc' });
        });

        it('attaches the async unique-name validator', () => {
            component.ngOnInit();
            expect(component.name.asyncValidator).toBeTruthy();
        });

        it('marks IPAM as available and maps the available special types', () => {
            premiumFeatureService.isAvailable$.and.returnValue(of(true));
            specialTypeService.getAvailableSpecialTypes.and.returnValue(of({ SUBNET: 'A subnet' }));

            component.ngOnInit();

            expect(premiumFeatureService.isAvailable$).toHaveBeenCalledWith(LicenseFeature.Ipam);
            expect(component.ipamAvailable).toBeTrue();
            expect(component.specialTypeOptions).toEqual([
                { value: SpecialType.SUBNET, label: 'SUBNET - A subnet', description: 'A subnet' }
            ]);
            expect(component.lockedSpecialTypeOptions[0].disabled).toBeTrue();
        });

        it('shows an error toast when loading available special types fails', () => {
            specialTypeService.getAvailableSpecialTypes.and.returnValue(
                throwError(() => ({ error: { message: 'boom' } }))
            );

            component.ngOnInit();

            expect(toastService.error).toHaveBeenCalledWith('boom');
        });
    });

    describe('edit mode initialization', () => {
        beforeEach(() => {
            component.mode = CmdbMode.Edit;
            component.typeInstance = buildType();
        });

        it('does not attach the async validator and does not query special types', () => {
            component.ngOnInit();
            expect(component.name.asyncValidator).toBeNull();
            expect(specialTypeService.getAvailableSpecialTypes).not.toHaveBeenCalled();
            expect(component.ipamAvailable).toBeFalse();
        });

        it('leaves the special type field hidden for a regular type', () => {
            component.ngOnInit();

            expect(component.hasAssignedSpecialType).toBeFalse();
            expect(component.assignedSpecialTypeOptions).toEqual([]);
            expect(component.specialType.disabled).toBeFalse();
            expect(specialTypeService.getAllSpecialTypes).not.toHaveBeenCalled();
        });
    });

    describe('edit mode: assigned special type', () => {
        beforeEach(() => {
            component.mode = CmdbMode.Edit;
        });

        it('selects the assigned special type and locks the control', () => {
            specialTypeService.getAllSpecialTypes.and.returnValue(of({
                SUBNET: 'IPAM - Subnet class',
                RACK: 'Rack View - Rack class'
            }));
            component.typeInstance = buildType({ special_type: SpecialType.SUBNET });

            component.ngOnInit();

            expect(component.hasAssignedSpecialType).toBeTrue();
            expect(component.specialType.value).toBe(SpecialType.SUBNET);
            expect(component.specialType.disabled).toBeTrue();
            expect(component.assignedSpecialTypeOptions).toEqual([{
                value: SpecialType.SUBNET,
                label: 'SUBNET - IPAM - Subnet class',
                description: 'IPAM - Subnet class'
            }]);
            expect(loaderService.show).toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
        });

        it('keeps the disabled value out of the submitted form value', () => {
            component.typeInstance = buildType({ special_type: SpecialType.RACK });

            component.ngOnInit();

            expect(component.form.value.special_type).toBeUndefined();
            expect(component.form.getRawValue().special_type).toBe(SpecialType.RACK);
        });

        it('does not write the special type back onto the type instance when other fields change', () => {
            component.typeInstance = buildType({ special_type: SpecialType.VLAN });

            component.ngOnInit();
            component.label.setValue('Renamed');

            expect(component.typeInstance.special_type).toBe(SpecialType.VLAN);
            expect(component.typeInstance.label).toBe('Renamed');
        });

        it('falls back to the bare token when the label lookup fails', () => {
            specialTypeService.getAllSpecialTypes.and.returnValue(throwError(() => new Error('offline')));
            component.typeInstance = buildType({ special_type: SpecialType.RACK });

            component.ngOnInit();

            expect(component.assignedSpecialTypeOptions).toEqual([{
                value: SpecialType.RACK,
                label: 'RACK',
                description: ''
            }]);
            expect(toastService.error).not.toHaveBeenCalled();
            expect(loaderService.hide).toHaveBeenCalled();
        });

        it('falls back to the bare token when the backend has no label for the token', () => {
            specialTypeService.getAllSpecialTypes.and.returnValue(of({ SUBNET: 'IPAM - Subnet class' }));
            component.typeInstance = buildType({ special_type: SpecialType.VLAN });

            component.ngOnInit();

            expect(component.assignedSpecialTypeOptions).toEqual([{
                value: SpecialType.VLAN,
                label: 'VLAN',
                description: ''
            }]);
        });

        it('ignores a blank special type value', () => {
            component.typeInstance = buildType({ special_type: '   ' as SpecialType });

            component.ngOnInit();

            expect(component.hasAssignedSpecialType).toBeFalse();
            expect(component.specialType.disabled).toBeFalse();
        });
    });

    describe('special type upgrade prompt', () => {
        it('delegates to the premium feature service for IPAM', () => {
            component.promptIpamUpgrade();
            expect(premiumFeatureService.promptUpgrade).toHaveBeenCalledWith(LicenseFeature.Ipam);
        });
    });

    describe('clearing the special type', () => {
        it('removes previously applied schema sections/fields and hides the loader', () => {
            component.typeInstance = buildType({
                special_type: SpecialType.SUBNET,
                fields: [{ name: 'ipam_fld' }, { name: 'user_fld' }],
                render_meta: {
                    icon: 'fa fa-cube',
                    sections: [
                        { type: 'section', name: 'ipam_sec', label: 'IPAM', fields: ['ipam_fld'] },
                        { type: 'section', name: 'user_sec', label: 'User', fields: ['user_fld'] }
                    ],
                    externals: [],
                    summary: { fields: [] }
                }
            });
            (component as any).specialTypeSchemaSectionNames = new Set(['ipam_sec']);
            (component as any).specialTypeSchemaFieldNames = new Set(['ipam_fld']);

            (component as any).handleSpecialTypeChange(null);

            expect(loaderService.hide).toHaveBeenCalled();
            expect(component.typeInstance.render_meta.sections.map((s) => s.name)).toEqual(['user_sec']);
            expect(component.typeInstance.fields.map((f: { name: string }) => f.name)).toEqual(['user_fld']);
            expect(component.typeInstance.special_type).toBeUndefined();
        });
    });
});
