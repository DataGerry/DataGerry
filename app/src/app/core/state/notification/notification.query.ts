import { Injectable } from '@angular/core';
import { Order, QueryEntity } from '@datorama/akita';
import { Notification, NotificationType } from './notification.model';
import { NotificationState, NotificationStore } from './notification.store';

@Injectable({ providedIn: 'root' })
export class NotificationQuery extends QueryEntity<NotificationState, Notification> {
  public readonly notifications$ = this.selectAll({
    sortBy: 'timestamp',
    sortByOrder: Order.DESC
  });

  constructor(protected override store: NotificationStore) {
    super(store);
  }

  public getByType(type: NotificationType): Notification[] {
    return this.getAll({
      filterBy: entity => entity.type === type,
      sortBy: 'timestamp',
      sortByOrder: Order.DESC
    });
  }
}

