import { ComponentFixture, TestBed, fakeAsync, tick } from "@angular/core/testing";
import { LoginComponent } from "./login.component"
import { FormsModule, ReactiveFormsModule } from "@angular/forms";
import { UserSettingsDBService } from "src/app/management/user-settings/services/user-settings-db.service";
import { AuthService } from "../services/auth.service";
import { PermissionService } from "../services/permission.service";
import { NgxIndexedDBService } from "ngx-indexed-db";
import { Renderer2 } from "@angular/core";
import { Router } from "@angular/router";
import { of } from "rxjs";
import { provideHttpClientTesting } from '@angular/common/http/testing';
import { provideHttpClient, withInterceptorsFromDi } from "@angular/common/http";




// Mock configuration for IndexedDB
const mockDbConfigs = {
    testDB: {
        name: 'testDB',
        version: 1,
        objectStoresMeta: [{
            store: 'testStore',
            storeConfig: { keyPath: 'id', autoIncrement: true },
            storeSchema: [
                { name: 'name', keypath: 'name', options: { unique: false } }
            ]
        }]
    }
};

// Mock platformId
const mockPlatformId = 'browser';

// Mock NgxIndexedDBService
class MockNgxIndexedDBService {
    add(storeName: string, value: any) {
        return of(value);
    }
}

describe('LoginComponent', () => {
    let component: LoginComponent;
    let fixture: ComponentFixture<LoginComponent>;


    beforeEach(() => {
        TestBed.configureTestingModule({
    declarations: [LoginComponent],
    imports: [ReactiveFormsModule, FormsModule],
    providers: [
        UserSettingsDBService,
        AuthService,
        PermissionService,
        { provide: NgxIndexedDBService, useClass: MockNgxIndexedDBService },
        { provide: 'dbConfigs', useValue: mockDbConfigs },
        { provide: 'PLATFORM_ID', useValue: mockPlatformId },
        { provide: Router, useValue: jasmine.createSpyObj('Router', ['navigate']) },
        Renderer2,
        provideHttpClient(withInterceptorsFromDi()),
        provideHttpClientTesting()
    ]
}).compileComponents();

        fixture = TestBed.createComponent(LoginComponent);
        component = fixture.componentInstance;
        fixture.detectChanges();
    });


    it('should create the form with 2 controls', () => {
        expect(component.loginForm.contains('username')).toBeTruthy();
        expect(component.loginForm.contains('password')).toBeTruthy();
    });


    it('should make namecontrol required', () => {
        let control = component.loginForm.get('username');
        control.setValue('');
        expect(control.valid).toBeFalsy();
    });


    it('should make password required', () => {
        let control = component.loginForm.get('password');
        control.setValue('');
        expect(control.valid).toBeFalsy();
    });

    xit('should submit the form if valid', fakeAsync(() => {
        spyOn(console, 'log');

        component.loginForm.setValue({ username: 'admin', password: 'admin' });

        component.onSubmit();
        tick();

        expect(component.submitted).toBeTruthy();
        expect(console.log).toHaveBeenCalledWith('Form submitted:', { username: 'admin', password: 'admin' });
    }));

});