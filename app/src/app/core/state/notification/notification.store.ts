import { Injectable } from '@angular/core';
import { EntityState, EntityStore, StoreConfig } from '@datorama/akita';
import { Notification } from './notification.model';

export interface NotificationState extends EntityState<Notification, string> {}

@Injectable({ providedIn: 'root' })
@StoreConfig({ name: 'notifications', idKey: 'id' })
export class NotificationStore extends EntityStore<NotificationState, Notification> {
  constructor() {
    super();
  }
}