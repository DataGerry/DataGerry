import { ComponentFixture, TestBed } from '@angular/core/testing';
import { SidebarCategoryComponent } from './sidebar-category.component';
import { By } from '@angular/platform-browser';
import { NO_ERRORS_SCHEMA } from '@angular/core';

describe('SidebarCategoryComponent', () => {
    let component: SidebarCategoryComponent;
    let fixture: ComponentFixture<SidebarCategoryComponent>;

    beforeEach(async () => {
        await TestBed.configureTestingModule({
            declarations: [SidebarCategoryComponent],
            schemas: [NO_ERRORS_SCHEMA] // Ignore unknown elements and attributes
        }).compileComponents();
    });

    beforeEach(() => {
        fixture = TestBed.createComponent(SidebarCategoryComponent);
        component = fixture.componentInstance;
    });

    it('should create the component', () => {
        expect(component).toBeTruthy();
    });

    it('should not render anchor if categoryNode is null', () => {
        component.categoryNode = null;
        fixture.detectChanges();
        const anchorElement = fixture.debugElement.query(By.css('a'));
        expect(anchorElement).toBeNull();
    });

    it('should render the category label in the anchor element', () => {
        component.categoryNode = {
            category: {
                name: 'category1',
                label: 'Category 1',
                meta: { icon: 'fas fa-icon', order: 1 },
                public_id: 1,
                parent: null,
                types: []
            },
            children: [],
            types: []
        };
        fixture.detectChanges();

        const anchorElement = fixture.debugElement.query(By.css('a'));
        expect(anchorElement.nativeElement.textContent).toContain('Category 1');
    });

    it('should toggle aria-expanded attribute on click', () => {
        component.categoryNode = {
            category: {
                name: 'category1',
                label: 'Category 1',
                meta: { icon: 'fas fa-icon', order: 1 },
                public_id: 1,
                parent: null,
                types: []
            },
            children: [],
            types: []
        };
        fixture.detectChanges();

        const anchorElement = fixture.debugElement.query(By.css('a'));
        expect(anchorElement.attributes['aria-expanded']).toBe('false');

        anchorElement.triggerEventHandler('click', null);
        fixture.detectChanges();
        expect(anchorElement.attributes['aria-expanded']).toBe('true');

        anchorElement.triggerEventHandler('click', null);
        fixture.detectChanges();
        expect(anchorElement.attributes['aria-expanded']).toBe('false');
    });

    it('should target the correct collapse element in the anchor element', () => {
        component.categoryNode = {
            category: {
                name: 'category1',
                label: 'Category 1',
                meta: { icon: 'fas fa-icon', order: 1 },
                public_id: 1,
                parent: null,
                types: []
            },
            children: [],
            types: []
        };
        fixture.detectChanges();

        const anchorElement = fixture.debugElement.query(By.css('a'));
        expect(anchorElement.nativeElement.getAttribute('data-bs-target')).toBe('#category1');
    });

    it('should render the ul element with the correct id', () => {
        component.categoryNode = {
            category: {
                name: 'category1',
                label: 'Category 1',
                meta: { icon: 'fas fa-icon', order: 1 },
                public_id: 1,
                parent: null,
                types: []
            },
            children: [],
            types: []
        };
        fixture.detectChanges();

        const ulElement = fixture.debugElement.query(By.css('ul'));
        expect(ulElement.nativeElement.id).toBe('category1');
    });

    it('should render nested cmdb-sidebar-category components for children', () => {
        component.categoryNode = {
            category: {
                name: 'category1',
                label: 'Category 1',
                meta: { icon: 'fas fa-icon', order: 1 },
                public_id: 1,
                parent: null,
                types: []
            },
            children: [{
                category: {
                    name: 'child1',
                    label: 'Child 1',
                    meta: { icon: 'fas fa-icon', order: 2 },
                    public_id: 2,
                    parent: 1,
                    types: []
                },
                children: [],
                types: []
            }],
            types: []
        };
        fixture.detectChanges();

        const childCategoryComponent = fixture.debugElement.query(By.directive(SidebarCategoryComponent));
        expect(childCategoryComponent).not.toBeNull();
    });

    it('should render "No types assigned" message when no children or types', () => {
        component.categoryNode = {
            category: {
                name: 'category1',
                label: 'Category 1',
                meta: { icon: 'fas fa-icon', order: 1 },
                public_id: 1,
                parent: null,
                types: []
            },
            children: [],
            types: []
        };
        fixture.detectChanges();

        const noTypesElement = fixture.debugElement.query(By.css('.list-group-item.disabled'));
        expect(noTypesElement.nativeElement.textContent).toContain('No types assigned');
    });
});
