/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2025 becon GmbH
*
* This program is free software: you can redistribute it and/or modify
* it under the terms of the GNU Affero General Public License as
* published by the Free Software Foundation, either version 3 of the
* License, or (at your option) any later version.
*
* This program is distributed in the hope that it will be useful,
* but WITHOUT ANY WARRANTY; without even the implied warranty of
* MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
* GNU Affero General Public License for more details.

* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/

import { Component, EventEmitter, Input, OnChanges, OnDestroy, OnInit, Output, SimpleChanges } from '@angular/core';
import { CmdbType } from '../../../models/cmdb-type';
import { SupportedExporterExtension } from '../../../../export/export-objects/model/supported-exporter-extension';
import { RenderResult } from '../../../models/cmdb-render';
import { Router } from '@angular/router';
import { environment } from 'src/environments/environment';
import { ObjectService } from 'src/app/framework/services/object.service';
import { catchError, debounceTime, interval, Observable, of, Subject, Subscription, takeUntil } from 'rxjs';

@Component({
  selector: 'cmdb-object-table-head',
  templateUrl: './object-table-head.component.html',
  styleUrls: ['./object-table-head.component.scss']
})
export class ObjectTableHeadComponent implements OnInit, OnDestroy, OnChanges {

  @Input() public selectedObjects: Array<RenderResult> = [];
  @Input() public selectedObjectsIDs: Array<number> = [];
  @Input() public formatList: SupportedExporterExtension[] = [];
  @Input() public totalResults: number = 0;

  @Output() public fileExport: EventEmitter<any> = new EventEmitter<any>();
  @Output() public manyObjectDeletes: EventEmitter<any> = new EventEmitter<any>();

  @Input() public type: CmdbType;

  totalObjects: number = 0;
  usedObjects: number;
  usedObjects$: Observable<number>;

  private fetchTrigger$ = new Subject<void>();
  private destroy$ = new Subject<void>();
  private subscription: Subscription;

  isCloudModeEnabled = environment.cloudMode;

  public constructor(private router: Router, private objectService: ObjectService) { }

  ngOnInit(): void {

    if(this.isCloudModeEnabled){
      this.subscription = this.objectService.getConfigItemsLimit().subscribe({
        next: (limit) => {
          this.totalObjects = limit;
        }
      });
  
      this.fetchTrigger$.pipe(
        debounceTime(300),
        takeUntil(this.destroy$)
      ).subscribe(() => {
        this.fetchUsedObjects();
      });
  
      this.fetchUsedObjects();
    }
  }


  ngOnChanges(changes: SimpleChanges): void {
    const relevantChanges = ['selectedObjects', 'selectedObjectsIDs', 'type'];

    const hasRelevantChange = relevantChanges.some(prop => changes[prop]);

    if (hasRelevantChange) {
      this.fetchTrigger$.next();
    }
  }


  ngOnDestroy(): void {
    this.destroy$?.next();
    this.destroy$?.complete();
    this.fetchTrigger$?.complete();

    if (this.subscription) {
      this.subscription.unsubscribe();
    }
  }


  /**
   * Fetch the count of used objects from the backend.
   */
  private fetchUsedObjects(): void {
    this.usedObjects$ = this.objectService.countObjects().pipe(
      catchError(error => {
        return of(0);
      })
    );

    this.usedObjects$.subscribe(count => {
      this.usedObjects = count;
    });
  }


  /**
   * Determines the CSS class for a button based on the usage percentage of objects.
   * @returns A string representing the button's CSS class.
   */
  getButtonClass(): string {
    if (!this.isCloudModeEnabled) {
      return 'btn btn-primary'; // Default Bootstrap button class
    }

    const percentage = this.calculatePercentage();

    if (percentage === 100 || percentage > 100) {
      return 'btn btn-secondary disabled-look';
    }
  }


  /**
   * Gets the tooltip text for the button based on usage percentage.
   */
  getButtonTooltip(): string {
    if (!this.isCloudModeEnabled) {
      return 'Add a new object';
    }
  
    const percentage = this.calculatePercentage();
    return percentage === 100 || percentage > 100
      ? 'Maximum number of objects has been reached'
      : 'Add a new object';
  }
  

  /**
  * Gets the tooltip text for the Bulk change button.
  */
  public getBulkChangeTooltip(): string | null {
    return this.selectedObjects.length === 0 ? 'No objects selected for bulk change' : null;
  }


  /**
  * Gets the tooltip text for the delete selected button.
  */
  public getDeleteSelectedTooltip(): string | null {
    return this.selectedObjects.length === 0 ? 'No objects selected for deletion' : null;
  }


  /**
   * Calculates the percentage of used objects.
   */
  private calculatePercentage(): number {
    return this.totalObjects > 0 ? (this.usedObjects / this.totalObjects) * 100 : 0;
  }


  public onBulkChange(): void {
    this.router.navigate(['/framework/object/change/'],
      { state: { type: this.type, objects: this.selectedObjects } });
  }

  public exporter(see: SupportedExporterExtension, view: string = 'native'): void {
    see.view = view;
    this.fileExport.emit(see);
  }
}
