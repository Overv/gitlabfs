# -*- coding: utf-8 -*-
"""File system operations handling for FUSE.

FUSE expects a standard set of operations to be handled to match the
expectations of the operating system. This module exposes such an operations
interface to properly expose the file system abstraction of GitLab.

"""

import errno

import fuse

from gitlabfs.resolver import EntityType

class Operations(fuse.LoggingMixIn, fuse.Operations):
    """Class implementing file system operations for FUSE.

    Note:
        This file system implementation uses only paths, no file handles.

    Attributes:
        resolver (gitlabfs.resolver.Resolver): Resolver of files and directories
            within the file system.

    """

    def __init__(self, resolver):
        """Initialize file system operations.

        Args:
            resolver (gitlabfs.resolver.Resolver): Resolver for the file system.

        """

        self.resolver = resolver

    def getattr(self, path, fh=None):
        """Get the attributes of a file or directory at the specified path.

        Args:
            path (str): Path to file/directory to retrieve attributes of.
            fh (int): Unused.

        """

        entity = self.resolver.resolve_path(path)

        if entity is None:
            raise fuse.FuseOSError(errno.ENOENT)
        else:
            return entity.attributes

    def readdir(self, path, fh=None):
        """List the names of entries in a directory.

        Args:
            path (str): Path to directory.
            fh (int): Unused.

        """

        entity = self.resolver.resolve_path(path)

        # Check if entity can be listed or return the appropriate error
        if entity is None:
            raise fuse.FuseOSError(errno.ENOENT)
        else:
            entries = self.resolver.list_members(entity)

            if entries is None:
                return fuse.FuseOSError(errno.ENOTDIR)
            else:
                return sorted(['.', '..'] + entries)

    def read(self, path, size, offset, fh=None):
        """Read the contents of a file.

        Args:
            path (str): Path to the file.
            size (int): Number of bytes to read.
            offset (int): Byte offset into file.

        """

        entity = self.resolver.resolve_path(path)

        if entity is None:
            raise fuse.FuseOSError(errno.ENOENT)
        elif entity.type == EntityType.REPOSITORY_FILE:
            # API does not support range requests
            contents = self.resolver.read_file(entity)
            return contents[offset:offset + size]
        else:
            raise fuse.FuseOSError(errno.EISDIR)