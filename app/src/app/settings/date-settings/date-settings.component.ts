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

* You should have received a copy of the GNU Affero General Public License
* along with this program. If not, see <https://www.gnu.org/licenses/>.
*/

import moment from 'moment';
import 'moment-timezone';
import { Component, OnDestroy, OnInit } from '@angular/core';
import { AbstractControl, UntypedFormControl, UntypedFormGroup, Validators } from '@angular/forms';
import { DateSettingsService } from '../services/date-settings.service';
import { finalize, takeUntil } from 'rxjs/operators';
import { ReplaySubject } from 'rxjs';
import { ToastService } from '../../layout/toast/toast.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Component({
    selector: 'cmdb-date-settings',
    templateUrl: './date-settings.component.html',
    styleUrls: ['./date-settings.component.scss'],
    standalone: false
})
export class DateSettingsComponent implements OnInit, OnDestroy {

  /**
   * Un-subscriber for `DateSettingsComponent`.
   * @private
   */
  private subscriber: ReplaySubject<void> = new ReplaySubject<void>();

  /**
   * All time zones of MomentTimezone
   */
  public tzNames: string[] = moment.tz.names();

  /**
   * Example view for date format with selected settings
   */
  public displayTzF: string;

  /**
   * ISO 8601 date formats
   */
  public formats: any[] = [
    {id: 'short', format: 'YYYY-MM-DD', view:  '2013-07-16'},
    {id: 'medium', format: 'YYYY-MM-DDTHH', view: '2013-07-16T19'},
    {id: 'mediumZ', format: 'YYYY-MM-DDTHHZ', view: '2013-07-16T19Z'},
    {id: 'long', format: 'YYYY-MM-DDTHH:mm', view: '2013-07-16T19:23'},
    {id: 'longZ', format: 'YYYY-MM-DDTHH:mmZ', view: '2013-07-16T19:23Z'},
    {id: 'full', format: 'YYYY-MM-DDTHH:mm:ss', view: '2013-07-16T19:23:51Z'},
    {id: 'fullZ', format: 'YYYY-MM-DDTHH:mm:ssZ', view: '2013-07-16T19:23:51Z'}
  ];

  /**
   * FromGroup Regional Settings
   */
  public regionalForm: UntypedFormGroup;

  public isLoading$ = this.loaderService.isLoading$;

  constructor(private dateSettingsService: DateSettingsService, 
              private toast: ToastService,
              private loaderService: LoaderService) {

    this.regionalForm = new UntypedFormGroup({
      date_format: new UntypedFormControl('YYYY-MM-DD', Validators.required),
      timezone: new UntypedFormControl(moment.tz.guess(true)),
    });
  }

  ngOnInit(): void {
    this.loaderService.show();
    this.dateSettingsService.getDateSettings().pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide())).subscribe((dateSettings: any) => {
      this.regionalForm.patchValue(dateSettings);
    });

    this.regionalForm.valueChanges.pipe(takeUntil(this.subscriber)).subscribe(() => {
      this.updateFormatView();
    });
    this.updateFormatView();
  }

  /**
   * return controller from formGroup by name
   */
  public getController(name: string): AbstractControl {
    return this.regionalForm.get(name);
  }

  /**
   * return current format value from formGroup
   */
  public get format(): string {
    return this.regionalForm.get('date_format').value;
  }

  /**
   * return current timezone value from formGroup
   */
  public get timezone(): string {
    return this.regionalForm.get('timezone').value;
  }

  /**
   * Update example view for date format with selected settings
   */
  public updateFormatView(): void {
    this.displayTzF = moment.tz(moment(), this.timezone).format(this.format);
  }

  /**
   * Display Time Difference to Time Zone – UTC
   * @param timezone
   */
  public utcToDeviceString(timezone: string): string {
    const utc = moment.tz(moment(), timezone).format('( UTC Z )');
    return timezone + ' ' + utc;
  }

  public onSave(): void {
    if (this.regionalForm.valid) {
      this.loaderService.show()
      this.dateSettingsService.postDateSettings(this.regionalForm.getRawValue())
        .pipe(takeUntil(this.subscriber), finalize(() => this.loaderService.hide())).subscribe(() => {
          this.toast.success('Date Settings config was updated!');
      });
    }
  }

  public ngOnDestroy(): void {
    this.subscriber?.next();
    this.subscriber?.complete();
  }
}
