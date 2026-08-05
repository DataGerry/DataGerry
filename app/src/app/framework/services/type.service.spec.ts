import { TestBed, fakeAsync, tick, flushMicrotasks } from '@angular/core/testing';
import { HttpResponse } from '@angular/common/http';
import { UntypedFormControl } from '@angular/forms';
import { of, throwError } from 'rxjs';

import { checkTypeExistsValidator, TypeService } from './type.service';
import { ApiCallService } from '../../services/api-call.service';
import { UserService } from '../../management/services/user.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { CmdbType } from '../models/cmdb-type';

/**
 * Builds a minimal but structurally valid CmdbType for service assertions.
 */
function buildType(overrides: Partial<CmdbType> = {}): CmdbType {
    return {
        public_id: 1,
        name: 'server',
        label: 'Server',
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

describe('checkTypeExistsValidator (async unique-name validation)', () => {
    let typeService: jasmine.SpyObj<TypeService>;

    beforeEach(() => {
        typeService = jasmine.createSpyObj<TypeService>('TypeService', ['getTypeByName']);
    });

    it('returns null (valid) when the name does not exist yet', fakeAsync(() => {
        typeService.getTypeByName.and.returnValue(of(null));

        let result: unknown = 'untouched';
        checkTypeExistsValidator(typeService, 500)(new UntypedFormControl('new-type'))
            .subscribe((value: unknown) => (result = value));

        tick(500);
        expect(typeService.getTypeByName).toHaveBeenCalledWith('new-type');
        expect(result).toBeNull();
    }));

    it('returns a typeExists error when the name is already taken', fakeAsync(() => {
        typeService.getTypeByName.and.returnValue(of(buildType({ name: 'server' })));

        let result: unknown = null;
        checkTypeExistsValidator(typeService, 500)(new UntypedFormControl('server'))
            .subscribe((value: unknown) => (result = value));

        tick(500);
        expect(result).toEqual({ typeExists: true });
    }));

    it('does not emit before the debounce time elapses', fakeAsync(() => {
        typeService.getTypeByName.and.returnValue(of(null));

        let emitted = false;
        checkTypeExistsValidator(typeService, 500)(new UntypedFormControl('server'))
            .subscribe(() => (emitted = true));

        tick(499);
        expect(typeService.getTypeByName).not.toHaveBeenCalled();
        expect(emitted).toBeFalse();

        tick(1);
        expect(emitted).toBeTrue();
    }));

    it('fails open (treats the name as valid) when the lookup errors', fakeAsync(() => {
        typeService.getTypeByName.and.returnValue(throwError(() => new Error('network down')));

        let result: unknown = 'untouched';
        checkTypeExistsValidator(typeService, 500)(new UntypedFormControl('server'))
            .subscribe((value: unknown) => (result = value));

        tick(500);
        flushMicrotasks();
        expect(result).toBeNull();
    }));

    it('honours a custom debounce time', fakeAsync(() => {
        typeService.getTypeByName.and.returnValue(of(null));

        checkTypeExistsValidator(typeService, 100)(new UntypedFormControl('server')).subscribe();

        tick(100);
        expect(typeService.getTypeByName).toHaveBeenCalledTimes(1);
    }));
});


describe('TypeService (type CRUD)', () => {
    let service: TypeService;
    let api: jasmine.SpyObj<ApiCallService>;
    let sidebar: jasmine.SpyObj<SidebarService>;

    beforeEach(() => {
        api = jasmine.createSpyObj<ApiCallService>('ApiCallService', [
            'callGet', 'callPost', 'callPut', 'callDelete', 'callHead'
        ]);
        sidebar = jasmine.createSpyObj<SidebarService>('SidebarService', ['loadCategoryTree']);

        const userService = {
            getCurrentUser: () => ({ public_id: 1, group_id: 1 })
        } as unknown as UserService;

        TestBed.configureTestingModule({
            providers: [
                TypeService,
                { provide: ApiCallService, useValue: api },
                { provide: UserService, useValue: userService },
                { provide: SidebarService, useValue: sidebar }
            ]
        });

        service = TestBed.inject(TypeService);
    });

    it('getType unwraps the single result payload', (done) => {
        const type = buildType({ public_id: 7, name: 'router' });
        api.callGet.and.returnValue(of(new HttpResponse({ body: { result: type } })));

        service.getType(7).subscribe((result) => {
            expect(result).toEqual(type);
            done();
        });
    });

    it('getTypeByName returns the first match', (done) => {
        const type = buildType({ name: 'server' });
        api.callGet.and.returnValue(of(new HttpResponse({ body: { count: 1, results: [type] } })));

        service.getTypeByName('server').subscribe((result) => {
            expect(result).toEqual(type);
            done();
        });
    });

    it('getTypeByName returns null when no type matches', (done) => {
        api.callGet.and.returnValue(of(new HttpResponse({ body: { count: 0, results: [] } })));

        service.getTypeByName('does-not-exist').subscribe((result) => {
            expect(result).toBeNull();
            done();
        });
    });

    it('postType sends the type and unwraps the raw response', (done) => {
        const created = buildType({ public_id: 42, name: 'switch' });
        api.callPost.and.returnValue(of(new HttpResponse({ body: { raw: created } })));

        service.postType(created).subscribe((result) => {
            expect(api.callPost).toHaveBeenCalled();
            const [url, payload] = api.callPost.calls.mostRecent().args;
            expect(url).toBe('types/');
            expect(payload).toBe(created);
            expect(result).toEqual(created);
            done();
        });
    });

    it('putType targets the type public_id and unwraps the result', (done) => {
        const updated = buildType({ public_id: 5, name: 'firewall' });
        api.callPut.and.returnValue(of(new HttpResponse({ body: { result: updated } })));

        service.putType(updated).subscribe((result) => {
            expect(api.callPut.calls.mostRecent().args[0]).toBe('types/5');
            expect(result).toEqual(updated);
            done();
        });
    });

    it('deleteType refreshes the sidebar category tree', (done) => {
        const deleted = buildType({ public_id: 9 });
        api.callDelete.and.returnValue(of(new HttpResponse({ body: { raw: deleted } })));

        service.deleteType(9).subscribe((result) => {
            expect(api.callDelete.calls.mostRecent().args[0]).toBe('types/9');
            expect(sidebar.loadCategoryTree).toHaveBeenCalled();
            expect(result).toEqual(deleted);
            done();
        });
    });
});
