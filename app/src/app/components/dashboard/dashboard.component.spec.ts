import { ComponentFixture, TestBed } from '@angular/core/testing';
import { DashboardComponent } from './dashboard.component';
import { By } from '@angular/platform-browser';
import { NO_ERRORS_SCHEMA, TemplateRef } from '@angular/core';
import { of, ReplaySubject, throwError } from 'rxjs';
import { takeUntil } from 'rxjs/operators';
import { RenderResult } from 'src/app/framework/models/cmdb-render';
import { ObjectService } from 'src/app/framework/services/object.service';
import { SidebarService } from 'src/app/layout/services/sidebar.service';
import { ToastService } from 'src/app/layout/toast/toast.service';
import { APIGetMultiResponse } from 'src/app/services/models/api-response';

describe('DashboardComponent', () => {
    let component: DashboardComponent;
    let fixture: ComponentFixture<DashboardComponent>;
    let objectServiceMock: any;
    let toastServiceMock: any;
    let sidebarServiceMock: any;

    beforeEach(async () => {
        objectServiceMock = jasmine.createSpyObj('ObjectService', ['countObjects', 'getLastObjectCount', 'getNewestObjects', 'getLatestObjects', 'deleteObject', 'deleteObjectWithLocations', 'deleteObjectWithChildren', 'groupObjectsByType']);
        toastServiceMock = jasmine.createSpyObj('ToastService', ['error', 'success']);
        sidebarServiceMock = jasmine.createSpyObj('SidebarService', ['updateTypeCounter']);

        await TestBed.configureTestingModule({
            declarations: [DashboardComponent],
            providers: [
                { provide: ObjectService, useValue: objectServiceMock },
                { provide: ToastService, useValue: toastServiceMock },
                { provide: SidebarService, useValue: sidebarServiceMock }
            ],
            schemas: [NO_ERRORS_SCHEMA]
        }).compileComponents();
    });

    beforeEach(() => {
        fixture = TestBed.createComponent(DashboardComponent);
        component = fixture.componentInstance;
        // Ensuring that each call to service methods returns an observable
        objectServiceMock.countObjects.and.returnValue(of(null));
        objectServiceMock.getLastObjectCount.and.returnValue(of(10));
        objectServiceMock.getNewestObjects.and.returnValue(of({ results: [], total: 10 } as APIGetMultiResponse<RenderResult>));
        objectServiceMock.getLatestObjects.and.returnValue(of({ results: [], total: 10 } as APIGetMultiResponse<RenderResult>));
        objectServiceMock.groupObjectsByType.and.returnValue(of([]));
        fixture.detectChanges();
    });

    it('should create the component', () => {
        expect(component).toBeTruthy();
    });

    describe('ngOnInit', () => {
        beforeEach(() => {
            component.ngOnInit();
            fixture.detectChanges();
        });

        it('should initialize table columns', () => {
            expect(component.newestTableColumns.length).toBeGreaterThan(0);
            expect(component.latestTableColumns.length).toBeGreaterThan(0);
        });

        it('should call countObjects', () => {
            expect(objectServiceMock.countObjects).toHaveBeenCalled();
            expect(component.objectCount).toBe(10);
        });

        it('should load newest objects', () => {
            expect(objectServiceMock.getNewestObjects).toHaveBeenCalled();
            expect(component.newestObjectsCount).toBe(10);
        });

        it('should load latest objects', () => {
            expect(objectServiceMock.getLatestObjects).toHaveBeenCalled();
            expect(component.latestObjectsCount).toBe(10);
        });

        it('should generate object chart', () => {
            expect(objectServiceMock.groupObjectsByType).toHaveBeenCalled();
        });
    });


    it('should handle error when deleting object', () => {
        const backendMessage = 'Error while deleting object';
        objectServiceMock.deleteObject.and.returnValue(throwError(() => ({ error: { message: backendMessage } })));
        const mockObject: RenderResult = { object_information: { object_id: 1 }, type_information: { type_id: 1 } } as RenderResult;
        component.onObjectDelete(mockObject);
        expect(toastServiceMock.error).toHaveBeenCalledWith(backendMessage);
    });

    describe('onLatestPageChange', () => {
        it('should update latestPage and call loadLatestObjects', () => {
            spyOn(component, 'loadLatestObjects' as any);
            const newPage: number = 2;
            component.onLatestPageChange(newPage);
            expect(component.latestPage).toBe(newPage);
            expect(component['loadLatestObjects']).toHaveBeenCalled();
        });
    });
});


