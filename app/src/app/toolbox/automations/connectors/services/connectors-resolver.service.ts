import { Injectable } from '@angular/core';
import { Resolve, ActivatedRouteSnapshot } from '@angular/router';
import { finalize, Observable, of } from 'rxjs';
import { Invoker } from '../models/invoker.model';
import { ConnectorsService } from './connectors.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Injectable({ providedIn: 'root' })
export class ConnectorsResolver implements Resolve<Invoker[]> {
  constructor(private svc: ConnectorsService,     
    private loaderService: LoaderService  ) {}
  
  resolve(route: ActivatedRouteSnapshot): Observable<Invoker[]> {
    
    // Check if we're in internal mode - skip API call for internal mode
    const mode = route.data['mode'] || history.state?.mode;
    
    if (mode === 'internal') {
      // For internal mode, return empty array since we don't need invoker data
      return of([]);
    }
    
    this.loaderService.show();
    return this.svc.getInvokers().pipe(
      finalize(() => this.loaderService.hide())
    );
  }
}
