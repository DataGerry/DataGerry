import { ComponentFixture, TestBed, waitForAsync } from '@angular/core/testing';
import { NO_ERRORS_SCHEMA } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { of } from 'rxjs';

import { CategoryViewComponent } from './category-view.component';
import { CategoryService } from '../../services/category.service';
import { TypeService } from '../../services/type.service';

describe('CategoryViewComponent', () => {
  let component: CategoryViewComponent;
  let fixture: ComponentFixture<CategoryViewComponent>;

  beforeEach(waitForAsync(() => {
    TestBed.configureTestingModule({
      declarations: [ CategoryViewComponent ],
      providers: [
        { provide: CategoryService, useValue: jasmine.createSpyObj('CategoryService', { getCategory: of(null) }) },
        { provide: TypeService, useValue: {} },
        { provide: ActivatedRoute, useValue: { params: of({}) } }
      ],
      schemas: [NO_ERRORS_SCHEMA]
    })
    .compileComponents();
  }));

  beforeEach(() => {
    fixture = TestBed.createComponent(CategoryViewComponent);
    component = fixture.componentInstance;
    fixture.detectChanges();
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });
});
