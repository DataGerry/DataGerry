import { Injectable } from '@angular/core';
import { Resolve } from '@angular/router';
import { finalize, Observable } from 'rxjs';
import { Invoker } from '../models/invoker.model';
import { ConnectorsService } from './connectors.service';
import { LoaderService } from 'src/app/core/services/loader.service';

@Injectable({ providedIn: 'root' })
export class ConnectorsResolver implements Resolve<Invoker[]> {
  constructor(private svc: ConnectorsService,     
    private loaderService: LoaderService  ) {}
  resolve(): Observable<Invoker[]> {
    this.loaderService.show();
    return this.svc.getInvokers().pipe(
      finalize(() => this.loaderService.hide())
    );
  }
}


