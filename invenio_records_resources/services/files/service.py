# -*- coding: utf-8 -*-
#
# Copyright (C) 2020 CERN.
# Copyright (C) 2020 Northwestern University.
#
# Invenio-Records-Resources is free software; you can redistribute it and/or
# modify it under the terms of the MIT License; see LICENSE file for more
# details.

"""Record Service API."""

from copy import deepcopy

from invenio_db import db
from invenio_files_rest.errors import FileSizeError
from invenio_files_rest.models import ObjectVersion

from ..records import RecordService
from ..records.schema import MarshmallowServiceSchema
from .config import RecordFileServiceConfig


# FIXME: Two functions and one property have to be prefixed `file_` to avoid
#        collisions when using the mixing e.g. along with a RecordService.
class FileServiceMixin:
    """File service mixin.

    This service is meant to work as a mixin, along a service that
    supports records. It is not meant to work as an standalone service.
    """

    default_config = None  # It is defined when the mixin is used.

    @property
    def file_schema(self):
        """Returns the data schema instance."""
        return MarshmallowServiceSchema(self, schema=self.config.file_schema)

    def file_result_item(self, *args, **kwargs):
        """Create a new instance of the resource unit."""
        return self.config.file_result_item_cls(*args, **kwargs)

    def file_result_list(self, *args, **kwargs):
        """Create a new instance of the resource list."""
        return self.config.file_result_list_cls(*args, **kwargs)

    @property
    def schema_files_links(self):
        """Returns the schema used for making search links."""
        return MarshmallowServiceSchema(
            self, schema=self.config.schema_files_links)

    #
    # High-level API
    #
    def list_files(self, id_, identity, links_config=None):
        """List the files of a record."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "read", record=record)
        return self.file_result_list(
            self,
            identity,
            results=record.files.values(),
            record=record,
            links_config=links_config,
        )

    def init_files(self, id_, identity, data, links_config=None):
        """Initialize the file upload for the record."""
        record = self.record_cls.pid.resolve(id_)
        # TODO implement permission, limit files?
        self.require_permission(identity, "create", record=record)
        # TODO: Load via marshmallow schema?
        results = []
        for file_metadata in data:
            temporary_obj = deepcopy(file_metadata)
            results.append(
                record.files.create(
                    temporary_obj.pop('key'), data=temporary_obj))
        # TODO: maybe do this automatically in the files field
        record.commit()
        db.session.commit()
        return self.file_result_list(
            self,
            identity,
            results,
            record,
            links_config,
        )

    def update_file_metadata(
            self, id_, file_key, identity, data, links_config=None):
        """Update the metadata of a file."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "create", record=record)
        rf = record.files.update(file_key, data=data)
        record.commit()
        db.session.commit()
        return self.file_result_item(
            self,
            identity,
            rf,
            links_config,
        )

    def read_file_metadata(self, id_, file_key, identity, links_config=None):
        """Read the metadata of a file."""
        record = self.record_cls.pid.resolve(id_)
        return self.file_result_item(
            self,
            identity,
            record.files[file_key],
            links_config,
        )

    # TODO: `commit_file` might vary based on your storage backend (e.g. S3)
    def commit_file(self, id_, file_key, identity, links_config=None):
        """Commit a file upload."""
        record = self.record_cls.pid.resolve(id_)
        file_obj = ObjectVersion.get(record.bucket.id, file_key)
        if not file_obj:
            raise Exception(f'File with key {file_key} not uploaded yet.')
        # TODO: Add other checks here (e.g. verify checksum, S3 upload)
        record.files[file_key] = file_obj
        record.commit()
        db.session.commit()
        return self.file_result_item(
            self,
            identity,
            record.files[file_key],
            links_config,
        )

    def delete_file(self, id_, file_key, identity, links_config=None):
        """Delete a single file."""
        record = self.record_cls.pid.resolve(id_)
        deleted_file = record.files.delete(file_key)
        record.commit()
        db.session.commit()
        return self.file_result_item(
            self,
            identity,
            deleted_file,
            links_config,
        )

    def delete_all_files(self, id_, identity, links_config=None):
        """Delete all the files of the record."""
        record = self.record_cls.pid.resolve(id_)
        self.require_permission(identity, "delete", record=record)
        results = []
        for file in record.files:
            results.append(record.files.delete(file.key))
        return self.file_result_list(
            self,
            identity,
            results,
            record,
            links_config,
        )

    def set_file_content(
            self, id_, file_key, identity, stream,
            content_length=None, links_config=None):
        """Save file content."""
        # TODO stream not exhausted
        record = self.record_cls.pid.resolve(id_)
        rf = record.files.get(file_key)
        if not rf or rf.file:
            # TODO bad request
            return {}

        bucket = record.bucket
        size_limit = bucket.size_limit
        if content_length and size_limit and content_length > size_limit:
            desc = 'File size limit exceeded.' \
                if isinstance(size_limit, int) else size_limit.reason
            raise FileSizeError(description=desc)
        # DB connection?
        # re uploading failed upload?

        with db.session.begin_nested():
            # TODO: in case we want to update a file, this keeps the old
            # FileInstance. It might be better to call ObjectVersion.remove()
            # before or after the "set_content"
            obj = ObjectVersion.create(bucket, file_key)
            obj.set_contents(
                stream, size=content_length, size_limit=size_limit)
        db.session.commit()
        return self.file_result_item(
            self,
            identity,
            record.files[file_key],
            links_config,
        )

    def get_file_content(self, id_, file_key, identity, links_config=None):
        """Retrieve file content."""
        record = self.record_cls.pid.resolve(id_)
        # TODO Signal here or in resource?
        # file_downloaded.send(file_obj)
        return self.file_result_item(
            self,
            identity,
            record.files[file_key],
            links_config,
        )


class RecordFileService(RecordService, FileServiceMixin):
    """Record service with files support."""

    default_config = RecordFileServiceConfig
