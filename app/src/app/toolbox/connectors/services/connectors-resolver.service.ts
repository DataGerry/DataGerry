import { Injectable } from '@angular/core';
import { Resolve } from '@angular/router';
import { Observable } from 'rxjs';
import { Invoker } from '../models/invoker.model';
import { ConnectorsService } from './connectors.service';

@Injectable({ providedIn: 'root' })
export class ConnectorsResolver implements Resolve<Invoker[]> {
  constructor(private svc: ConnectorsService) {}
  resolve(): Observable<Invoker[]> {
    return this.svc.getInvokers();
  }
}
