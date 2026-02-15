/*
* DATAGERRY - OpenSource Enterprise CMDB
* Copyright (C) 2026 becon GmbH
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
*
* You should have received a copy of the GNU Affero General Public License
* along with this program.  If not, see <https://www.gnu.org/licenses/>.
*/
import { Component } from '@angular/core';
import { catchError, debounceTime, Observable, of, Subject, Subscription, takeUntil } from 'rxjs';
import { ObjectService } from 'src/app/framework/services/object.service';
import { environment } from 'src/environments/environment';

@Component({
    selector: 'cmdb-import',
    templateUrl: './import.component.html',
    styleUrls: ['./import.component.scss'],
    standalone: false
})
export class ImportComponent {

    totalObjects: number = 0;
    usedObjects: number;
    usedObjects$: Observable<number>;

    private fetchTrigger$ = new Subject<void>();
    private destroy$ = new Subject<void>();
    private subscription: Subscription;

    isCloudModeEnabled = environment.cloudMode;


    public constructor(private objectService: ObjectService) { }


    ngOnInit(): void {

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


    ngOnDestroy(): void {

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

        if (percentage === 100) {
            return 'btn btn-secondary disabled-look';
        }
    }


    /**
     * Calculates the percentage of used objects.
     */
    private calculatePercentage(): number {
        return this.totalObjects > 0 ? (this.usedObjects / this.totalObjects) * 100 : 0;
    }

    /**
     * Gets the tooltip text for the button based on usage percentage.
     */
    getButtonTooltip(): string {
        const percentage = this.calculatePercentage();

        if (percentage === 100) {
            return 'Maximum number of objects has been reached';
        }

        return 'Import Objects';
    }
}