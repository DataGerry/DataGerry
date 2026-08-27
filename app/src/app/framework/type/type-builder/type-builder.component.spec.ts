import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { of, throwError } from 'rxjs';

import { TypeBuilderComponent } from './type-builder.component';
import { TypeService } from '../../services/type.service';
import { UserService } from '../../../management/services/user.service';
import { ToastService } from '../../../layout/toast/toast.service';
import { GroupService } from '../../../management/services/group.service';
import { SidebarService } from '../../../layout/services/sidebar.service';
import { ValidationService } from 'src/app/framework/builder/services/validation.service';
import { LoaderService } from 'src/app/core/services/loader.service';
import { CmdbMode } from '../../modes.enum';
import { CmdbType } from '../../models/cmdb-type';
import { AccessControlList } from 'src/app/modules/acl/acl.types';

function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        public_id: 5,
        name: 'server',
        label: 'Server',
        active: true,
        version: '1.0.0',
        fields: [],
        acl: new AccessControlList(false, { includes: {} }),
        render_meta: {
            icon: 'fa fa-cube',
            sections: [],
            externals: [],
            summary: { fields: [] }
        },
        ...overrides
    } as CmdbType;
}

/**
 * Forces every save-gating flag into the "green" state so saveType() proceeds.
 */
function enableSave(component: TypeBuilderComponent): void {
    component.basicValid = true;
    component.contentValid = true;
    component.metaValid = true;
    component.accessValid = true;
    component.isLabelValid = true;
    component.isNameValid = true;
    component.isSectionHighlighted = false;
    component.isFieldHighlighted = false;
    component.disableFields = false;
    component.isSectionWithoutFields = true;
}

describe('TypeBuilderComponent (type creation wizard)', () => {
    let component: TypeBuilderComponent;
    let fixture: ComponentFixture<TypeBuilderComponent>;

    let router: jasmine.SpyObj<Router>;
    let typeService: jasmine.SpyObj<TypeService>;
    let toast: jasmine.SpyObj<ToastService>;
    let userService: jasmine.SpyObj<UserService>;
    let groupService: jasmine.SpyObj<GroupService>;
    let sidebarService: jasmine.SpyObj<SidebarService>;
    let loaderService: jasmine.SpyObj<LoaderService>;

    beforeEach(async () => {
        router = jasmine.createSpyObj<Router>('Router', ['navigate']);
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypes', 'postType', 'putType']);
        toast = jasmine.createSpyObj<ToastService>('ToastService', ['success', 'error']);
        userService = jasmine.createSpyObj<UserService>('UserService', ['getCurrentUser']);
        groupService = jasmine.createSpyObj<GroupService>('GroupService', ['getGroups']);
        sidebarService = jasmine.createSpyObj<SidebarService>('SidebarService', ['loadCategoryTree']);
        loaderService = jasmine.createSpyObj<LoaderService>('LoaderService', ['show', 'hide'], { isLoading$: of(false) });

        userService.getCurrentUser.and.returnValue({ public_id: 7 } as any);
        groupService.getGroups.and.returnValue(of({ results: [{ public_id: 1 }], total: 1, count: 1 } as any));
        typeService.getTypes.and.returnValue(of({ results: [{ public_id: 10, name: 'x' }], total: 1, count: 1 } as any));

        await TestBed.configureTestingModule({
            declarations: [TypeBuilderComponent],
            providers: [
                ValidationService,
                { provide: Router, useValue: router },
                { provide: TypeService, useValue: typeService },
                { provide: ToastService, useValue: toast },
                { provide: UserService, useValue: userService },
                { provide: GroupService, useValue: groupService },
                { provide: SidebarService, useValue: sidebarService },
                { provide: LoaderService, useValue: loaderService }
            ]
        })
            .overrideComponent(TypeBuilderComponent, { set: { template: '' } })
            .compileComponents();

        fixture = TestBed.createComponent(TypeBuilderComponent);
        component = fixture.componentInstance;
    });

    describe('create mode initialization', () => {
        it('bootstraps a fresh, inactive-ACL type owned by the current user', () => {
            component.mode = CmdbMode.Create;

            component.ngOnInit();

            expect(component.typeInstance.active).toBeTrue();
            expect(component.typeInstance.version).toBe('1.0.0');
            expect(component.typeInstance.author_id).toBe(7);
            expect(component.typeInstance.render_meta.sections).toEqual([]);
            expect(component.typeInstance.render_meta.summary.fields).toEqual([]);
            expect(component.typeInstance.ci_explorer_label).toBeNull();
            expect(component.typeInstance.acl.activated).toBeFalse();
        });

        it('loads the available groups and types', () => {
            component.mode = CmdbMode.Create;
            component.ngOnInit();

            expect(component.groups.length).toBe(1);
            expect(component.types.length).toBe(1);
        });
    });

    describe('isSaveButtonDisabled', () => {
        it('is disabled by default (no completed sections yet)', () => {
            expect(component.isSaveButtonDisabled).toBeTrue();
        });

        it('is enabled when every step is valid and there are no highlight/blocking states', () => {
            enableSave(component);
            expect(component.isSaveButtonDisabled).toBeFalse();
        });

        it('is disabled when the basic step is invalid', () => {
            enableSave(component);
            component.basicValid = false;
            expect(component.isSaveButtonDisabled).toBeTrue();
        });

        it('is disabled when a section is highlighted (unresolved editing)', () => {
            enableSave(component);
            component.isSectionHighlighted = true;
            expect(component.isSaveButtonDisabled).toBeTrue();
        });

        it('is disabled when fields are disabled', () => {
            enableSave(component);
            component.disableFields = true;
            expect(component.isSaveButtonDisabled).toBeTrue();
        });
    });

    describe('saveType() in create mode', () => {
        beforeEach(() => {
            component.mode = CmdbMode.Create;
            component.ngOnInit();
            component.typeInstance.render_meta.sections = [
                { type: 'section', name: 's1', label: 'S1', fields: [{ name: 'f1' }, 'f2'] }
            ];
            enableSave(component);
        });

        it('flattens section fields to names, posts the type and reports success', () => {
            typeService.postType.and.returnValue(of({ public_id: 42 } as any));

            component.saveType();

            const posted = typeService.postType.calls.mostRecent().args[0];
            expect(posted.render_meta.sections[0].fields).toEqual(['f1', 'f2']);
            expect(posted.editor_id).toBeUndefined();
            expect(loaderService.show).toHaveBeenCalled();
            expect(router.navigate).toHaveBeenCalledWith(['/framework/type/'], { queryParams: { typeAddSuccess: 42 } });
            expect(sidebarService.loadCategoryTree).toHaveBeenCalled();
            expect(toast.success).toHaveBeenCalled();
        });

        it('surfaces the backend error message when creation fails', () => {
            typeService.postType.and.returnValue(throwError(() => ({ error: { message: 'name already taken' } })));

            component.saveType();

            expect(toast.error).toHaveBeenCalledWith('name already taken');
            expect(loaderService.hide).toHaveBeenCalled();
        });
    });

    describe('saveType() guard', () => {
        it('refuses to save and warns the user when the form is incomplete', () => {
            component.mode = CmdbMode.Create;
            component.ngOnInit();
            // isSectionWithoutFields stays false -> save button disabled

            component.saveType();

            expect(toast.error).toHaveBeenCalledWith('Form is invalid or incomplete. Cannot save.');
            expect(typeService.postType).not.toHaveBeenCalled();
        });
    });

    describe('saveType() in edit mode', () => {
        it('stamps the editor id, updates the type and reports success', () => {
            component.mode = CmdbMode.Edit;
            component.typeInstance = buildType({ public_id: 5 });
            component.ngOnInit();
            component.typeInstance.render_meta.sections = [
                { type: 'section', name: 's1', label: 'S1', fields: ['f1'] }
            ];
            enableSave(component);
            typeService.putType.and.returnValue(of({ public_id: 5 } as any));

            component.saveType();

            const updated = typeService.putType.calls.mostRecent().args[0];
            expect(updated.editor_id).toBe(7);
            expect(router.navigate).toHaveBeenCalledWith(['/framework/type/'], { queryParams: { typeEditSuccess: 5 } });
            expect(toast.success).toHaveBeenCalled();
        });
    });

    describe('ACL group existence check', () => {
        it('warns when an ACL references a group that no longer exists', () => {
            component.mode = CmdbMode.Edit;
            component.typeInstance = buildType({
                acl: { activated: true, groups: { includes: { 99: [] } } } as any
            });

            component.ngOnInit();

            expect(toast.error).toHaveBeenCalledWith('The group for the ACL setting does not exist: GroupID: 99');
        });
    });
});
