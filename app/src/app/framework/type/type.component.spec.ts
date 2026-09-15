/**
 * Covers the special-type column of the type list: its table configuration, the one-off label
 * lookup that feeds the badge, and what the column cell renders for special and regular types.
 */
import { CommonModule } from '@angular/common';
import { NO_ERRORS_SCHEMA, Pipe, PipeTransform } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { EmbeddedViewRef } from '@angular/core';
import { of, throwError } from 'rxjs';

import { TypeComponent } from './type.component';
import { SpecialTypeBadgeComponent } from 'src/app/layout/helpers/special-type-badge/special-type-badge.component';
import { TypeService } from '../services/type.service';
import { SpecialTypeService } from '../services/special-type.service';
import { FileService } from '../../export/export.service';
import { PermissionService } from '../../modules/auth/services/permission.service';
import { UserSettingsService } from '../../management/user-settings/services/user-settings.service';
import { UserSettingsDBService } from '../../management/user-settings/services/user-settings-db.service';
import { ExportDownloadService } from 'src/app/core/services/export-download.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { Column } from '../../layout/table/table.types';
import { SpecialType } from '../models/special-type';

@Pipe({ name: 'dateFormatter', standalone: false })
class DateFormatterStubPipe implements PipeTransform {
    transform(value: unknown): unknown {
        return value;
    }
}

const ALL_SPECIAL_TYPES = {
    SUPERNET: 'IPAM - Supernet class',
    SUBNET: 'IPAM - Subnet class',
    VLAN: 'IPAM - VLAN class',
    RACK: 'Rack View - Rack class'
};

describe('TypeComponent - special type column', () => {
    let component: TypeComponent;
    let fixture: ComponentFixture<TypeComponent>;

    let typeService: jasmine.SpyObj<TypeService>;
    let specialTypeService: jasmine.SpyObj<SpecialTypeService>;
    let loaderService: LoaderService;

    const columnFor = (name: string): Column | undefined =>
        component.columns.find((column) => column.name === name);

    /** Renders the special-type cell template with the value the table would hand it. */
    const renderCell = (data: unknown): HTMLElement => {
        const view: EmbeddedViewRef<unknown> = component.specialTypeTemplate.createEmbeddedView({ data });
        view.detectChanges();

        const host = document.createElement('div');
        view.rootNodes.forEach((node: Node) => host.appendChild(node));
        return host;
    };

    beforeEach(async () => {
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypesOverview']);
        typeService.getTypesOverview.and.returnValue(of({ results: [], total: 0 } as never));

        specialTypeService = jasmine.createSpyObj<SpecialTypeService>('SpecialTypeService', ['getAllSpecialTypes']);
        specialTypeService.getAllSpecialTypes.and.returnValue(of(ALL_SPECIAL_TYPES));

        const permissionService = jasmine.createSpyObj<PermissionService>('PermissionService', [
            'hasRight', 'hasExtendedRight'
        ]);
        permissionService.hasRight.and.returnValue(false);
        permissionService.hasExtendedRight.and.returnValue(false);

        const userSettingsService = jasmine.createSpyObj<UserSettingsService<never, never>>(
            'UserSettingsService', ['createUserSetting']
        );
        userSettingsService.createUserSetting.and.returnValue({} as never);

        await TestBed.configureTestingModule({
            declarations: [TypeComponent, SpecialTypeBadgeComponent, DateFormatterStubPipe],
            imports: [CommonModule],
            providers: [
                LoaderService,
                { provide: TypeService, useValue: typeService },
                { provide: SpecialTypeService, useValue: specialTypeService },
                { provide: FileService, useValue: jasmine.createSpyObj<FileService>('FileService', ['getTypeFile', 'callExportTypeRoute']) },
                { provide: ActivatedRoute, useValue: { data: of({}) } },
                { provide: Router, useValue: { url: '/framework/type' } },
                { provide: PermissionService, useValue: permissionService },
                { provide: ExportDownloadService, useValue: jasmine.createSpyObj<ExportDownloadService>('ExportDownloadService', ['save']) },
                { provide: UserSettingsService, useValue: userSettingsService },
                { provide: UserSettingsDBService, useValue: jasmine.createSpyObj<UserSettingsDBService<never, never>>('UserSettingsDBService', ['addSetting']) },
                { provide: ToastService, useValue: jasmine.createSpyObj<ToastService>('ToastService', ['error', 'success']) }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        fixture = TestBed.createComponent(TypeComponent);
        component = fixture.componentInstance;
        loaderService = TestBed.inject(LoaderService);
    });

    describe('table configuration', () => {
        beforeEach(() => fixture.detectChanges());

        it('adds a sortable, template driven special type column bound to special_type', () => {
            const column = columnFor('special_type');

            expect(column).toBeDefined();
            expect(column.display).toBe('Special type');
            expect(column.data).toBe('special_type');
            expect(column.sortable).toBeTrue();
            expect(column.searchable).toBeFalse();
            expect(column.template).toBe(component.specialTypeTemplate);
        });

        it('places the column right after the type name', () => {
            const names = component.columns.map((column) => column.name);

            expect(names.indexOf('special_type')).toBe(names.indexOf('name') + 1);
        });

        it('keeps the special type out of the free text search', () => {
            const searchable = component.columns.filter((column) => column.searchable).map((column) => column.data);

            expect(searchable).not.toContain('special_type');
        });
    });

    describe('special type labels', () => {
        it('loads every label once, around the loader', () => {
            const show = spyOn(loaderService, 'show').and.callThrough();
            const hide = spyOn(loaderService, 'hide').and.callThrough();

            fixture.detectChanges();

            expect(specialTypeService.getAllSpecialTypes).toHaveBeenCalledTimes(1);
            expect(component.specialTypeLabels).toEqual(ALL_SPECIAL_TYPES);
            expect(show).toHaveBeenCalled();
            expect(hide).toHaveBeenCalled();
        });

        it('degrades to empty labels without a toast when the lookup fails', () => {
            specialTypeService.getAllSpecialTypes.and.returnValue(throwError(() => new Error('offline')));
            const toastService = TestBed.inject(ToastService) as jasmine.SpyObj<ToastService>;

            fixture.detectChanges();

            expect(component.specialTypeLabels).toEqual({});
            expect(toastService.error).not.toHaveBeenCalled();
        });

        it('hides the loader again when the lookup fails', () => {
            specialTypeService.getAllSpecialTypes.and.returnValue(throwError(() => new Error('offline')));
            const hide = spyOn(loaderService, 'hide').and.callThrough();

            fixture.detectChanges();

            expect(hide).toHaveBeenCalled();
        });

        it('tolerates an empty backend response', () => {
            specialTypeService.getAllSpecialTypes.and.returnValue(of(null as never));

            fixture.detectChanges();

            expect(component.specialTypeLabels).toEqual({});
        });
    });

    describe('column cell', () => {
        beforeEach(() => fixture.detectChanges());

        it('renders a badge with the backend label for a special type', () => {
            const cell = renderCell(SpecialType.RACK);
            const badge = cell.querySelector('.special-type-badge');

            expect(badge).not.toBeNull();
            expect(badge.textContent).toContain('Rack');
            expect(badge.querySelector('.visually-hidden').textContent).toContain('Rack View - Rack class');
        });

        it('does not resolve inherited object keys as a label', () => {
            expect(component.resolveSpecialTypeLabel('constructor')).toBe('');
            expect(component.resolveSpecialTypeLabel('toString')).toBe('');
            expect(component.resolveSpecialTypeLabel('RACK')).toBe('Rack View - Rack class');
        });

        it('leaves the cell empty for a regular type', () => {
            const cell = renderCell(undefined);

            expect(cell.querySelector('.special-type-badge')).toBeNull();
            expect(cell.textContent.trim()).toBe('');
        });
    });
});
