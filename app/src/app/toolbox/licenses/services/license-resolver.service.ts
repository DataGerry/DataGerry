import { Injectable } from '@angular/core';
import { Resolve } from '@angular/router';
import { finalize, Observable } from 'rxjs';
import { LicenseInfoResponse } from '../models/license.model';
import { LicenseService } from './license.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Injectable({ providedIn: 'root' })
export class LicenseResolver implements Resolve<LicenseInfoResponse> {
  constructor(
    private licenseService: LicenseService,
    private loaderService: LoaderService
  ) {}

  resolve(): Observable<LicenseInfoResponse> {
    this.loaderService.show();
    // Use default pagination for initial load (page 0, size 5)
    return this.licenseService.getLicenseInfo(0, 5).pipe(
      finalize(() => this.loaderService.hide())
    );
  }
}
