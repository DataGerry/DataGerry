import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SidebarComponent } from './sidebar.component';
import { SidebarService } from '../../services/sidebar.service';
import { TypeService } from '../../../framework/services/type.service';
import { UserService } from '../../../management/services/user.service';
import { By } from '@angular/platform-browser';
import { Renderer2, ElementRef, NO_ERRORS_SCHEMA } from '@angular/core';
import { of, ReplaySubject } from 'rxjs';
import { CmdbCategoryTree } from '../../../framework/models/cmdb-category';
import { APIGetMultiResponse } from '../../../services/models/api-response';
import { CmdbType } from 'src/app/framework/models/cmdb-type';
import { provideHttpClient, withInterceptorsFromDi } from '@angular/common/http';
import { provideHttpClientTesting } from '@angular/common/http/testing';

class MockElementRef extends ElementRef {
    constructor() {
        super(null);
    }
}

describe('SidebarComponent', () => {
    let component: SidebarComponent;
    let fixture: ComponentFixture<SidebarComponent>;
    let sidebarService: SidebarService;
    let typeService: TypeService;
    let userService: UserService;

    beforeEach(async () => {
        const sidebarServiceMock = {
            loadCategoryTree: jasmine.createSpy('loadCategoryTree'),
            categoryTree: new ReplaySubject<CmdbCategoryTree>(1),
            selectedMenu: 'categories'
        };

        const typeServiceMock = {
            getUncategorizedTypes: jasmine.createSpy('getUncategorizedTypes').and.returnValue(of({
                results: []
            } as APIGetMultiResponse<CmdbType>)),
            getTypes: jasmine.createSpy('getTypes').and.returnValue(of({
                results: []
            } as APIGetMultiResponse<CmdbType>))
        };

        const userServiceMock = {
            getCurrentUser: jasmine.createSpy('getCurrentUser').and.returnValue({} as any)
        };

        await TestBed.configureTestingModule({
            declarations: [SidebarComponent],
            providers: [
                { provide: SidebarService, useValue: sidebarServiceMock },
                { provide: TypeService, useValue: typeServiceMock },
                { provide: UserService, useValue: userServiceMock },
                Renderer2,
                { provide: ElementRef, useClass: MockElementRef },
                provideHttpClient(withInterceptorsFromDi()),
                provideHttpClientTesting()
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();

        sidebarService = TestBed.inject(SidebarService);
        typeService = TestBed.inject(TypeService);
        userService = TestBed.inject(UserService);
    });


    beforeEach(() => {
        fixture = TestBed.createComponent(SidebarComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();
    });


    it('should create', () => {
        expect(component).toBeTruthy();
    });


    it('should initialize and call loadCategoryTree', () => {
        expect(sidebarService.loadCategoryTree).toHaveBeenCalled();
    });


    it('should toggle sidebar expansion state', () => {
        const expandButton = fixture.debugElement.query(By.css('#expand-button'));
        if (expandButton) {
            expandButton.nativeElement.click();
            fixture.detectChanges();
            expect(component.isExpanded).toBeTrue();

            expandButton.nativeElement.click();
            fixture.detectChanges();
            expect(component.isExpanded).toBeFalse();
        }
    });


    it('should update selected menu on click', () => {
        const categoriesLabel = fixture.debugElement.query(By.css('.sidebar-menu-item[value="categories"]'));
        const locationsLabel = fixture.debugElement.query(By.css('.sidebar-menu-item[value="locations"]'));

        if (categoriesLabel) {
            categoriesLabel.nativeElement.click();
            fixture.detectChanges();
            expect(component.selectedMenu).toBe('categories');
            expect(sidebarService.selectedMenu).toBe('categories');
        }

        if (locationsLabel) {
            locationsLabel.nativeElement.click();
            fixture.detectChanges();
            expect(component.selectedMenu).toBe('locations');
            expect(sidebarService.selectedMenu).toBe('locations');
        }
    });


    it('should reset filter term', () => {
        component.filterTerm.setValue('test');
        fixture.detectChanges();
        const clearButton = fixture.debugElement.query(By.css('.fa-times'));
        if (clearButton) {
            clearButton.nativeElement.click();
            fixture.detectChanges();
            expect(component.filterTerm.value).toBe('');
        }
    });

});
