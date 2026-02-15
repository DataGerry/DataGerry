import { Component, Input, OnInit } from '@angular/core';
import { NgbActiveModal } from '@ng-bootstrap/ng-bootstrap';
import { FileElement } from '../../model/file-element';
import { BehaviorSubject } from 'rxjs';
import { ObjectService } from '../../../../../framework/services/object.service';
import { TypeService } from '../../../../../framework/services/type.service';
import { UserService } from '../../../../../management/services/user.service';

@Component({
    selector: 'cmdb-metadata-info',
    templateUrl: './metadata-info.component.html',
    styleUrls: ['./metadata-info.component.scss'],
    standalone: false
})
export class MetadataInfoComponent implements OnInit {

  /**
   * Data sharing between components
   */
  @Input() folderTree: FileElement[] = [];
  @Input() fileElement: FileElement;

  public selectedFileFolder: BehaviorSubject<any> = new BehaviorSubject<any>(null);
  public username: string;
  public refId: number[];

  constructor(public activeModal: NgbActiveModal, private objectService: ObjectService,
              private typeService: TypeService, private userService: UserService) {}

  ngOnInit(): void {
    const tempFile: any = Object.assign({}, this.fileElement);
    tempFile.public_id = this.fileElement.metadata.parent;
    this.selectedFileFolder.next(tempFile);

    this.userService.getUser(this.fileElement.metadata.author_id).subscribe(user => {
      this.username = `${user.user_name}`;
    });

    const tempId = this.fileElement.metadata.reference;
    this.refId = typeof tempId === 'number' ? [tempId] : tempId;
  }

}
