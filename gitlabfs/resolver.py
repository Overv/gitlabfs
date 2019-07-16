# -*- coding: utf-8 -*-
"""File system abstraction of GitLab.

This module contains the implementation of abstracting GitLab as a file system
hierarchy.

"""

from enum import Enum
import os.path
import pathlib
import stat
import time

import gitlab
import iso8601

def create_file_attributes(permissions, time, size):
    """Create a dictionary with file attributes for FUSE.

    Args:
        permissions (int): Permission bits for the file (e.g. 0o777).
        time (float): Unix timestamp of the last file modification.
        size (int): Size of the file in bytes.

    """

    return {
        'st_mode': (stat.S_IFREG | permissions),
        'st_ctime': time,
        'st_mtime': time,
        'st_atime': time,
        'st_size': size,
        'st_uid': os.getuid(),
        'st_gid': os.getgid(),
        'st_nlink': 1
    }

def create_directory_attributes(time):
    """Create a dictionary with directory attributes for FUSE.

    Args:
        time (int): Unix timestamp of the last directory modification.

    """

    return {
        'st_mode': (stat.S_IFDIR | 0o555),
        'st_ctime': time,
        'st_mtime': time,
        'st_atime': time,
        'st_uid': os.getuid(),
        'st_gid': os.getgid(),
        'st_nlink': 2
    }

class EntityType(Enum):
    """Types of entities in GitLab exposed as file system objects."""

    ROOT = 0
    GROUP = 1
    USER = 2
    PROJECT = 3
    REF_LEVEL = 4
    REPOSITORY_FILE = 5
    REPOSITORY_DIR = 6

class Entity:
    """Class that represents an entity in GitLab for the file system.

    Attributes:
        type (EntityType): Type of GitLab entity.
        path (str): Full path to entity within the file system.
        attributes (dict): FUSE attributes.
        objects (dict): API objects associated with entity - if any.

    """

    def __init__(self, type, path, attributes, objects={}):
        """Initialize representation of GitLab entity.

        Args:
            type (EntityType): Type of GitLab entity.
            path (str): Full path to entity within the file system.
            attributes (dict): FUSE attributes.
            objects (dict): API objects associated with entity - if any.

        """

        self.type = type
        self.path = path
        self.attributes = attributes
        self.objects = objects

class Resolver:
    """Class that resolves paths to objects within GitLab.

    This class manages abstraction of representing objects within GitLab as a
    file system hierarchy. This abstraction looks like the following:

    /gitlab
        /user
            /project
                /master
                    /README.md
                /feature
                    /abc
                        /src
                            main.py
        /group
            /subgroup
                /project

    Attributes:
        cache (gitlabfs.Cache): Cached API wrapper for GitLab.
        userProjects (bool): Include user projects.
        tagRefs (bool): Include tags in project refs.
        commitTimes (bool): Better approximate repository file times using their
            last commit time.
        initTime (float): Instantiation time of the file system.

    """

    def __init__(self, cache, userProjects, tagRefs, commitTimes):
        """Initialize the file system resolver.

        Args:
            cache (gitlabfs.cache.Cache): Cached GitLab API wrapper.
            userProjects (bool): Include user projects.
            tagRefs (bool): Include tags in project refs.
            commitTimes (bool): Better approximate repository file times using
                their last commit time.

        """

        self.cache = cache
        self.userProjects = userProjects
        self.tagRefs = tagRefs
        self.commitTimes = commitTimes

        self.initTime = time.time()

    def resolve_root(self, path):
        """Try to resolve a path as the root of GitLab.

        Args:
            path (str): Path into the file system.

        """

        if path == '/':
            return Entity(
                EntityType.ROOT,
                path,
                create_directory_attributes(self.initTime)
            )
        else:
            return None

    def resolve_tree(self, path):
        """Try to resolve a path as the root of a project, group or user.

        Args:
            path (str): Path into the file system.

        """

        try:
            node = self.cache.get_tree(self.userProjects)[path]

            if type(node) is gitlab.v4.objects.Group:
                # Groups API does not return a creation time
                return Entity(
                    EntityType.GROUP,
                    path,
                    create_directory_attributes(self.initTime),
                    {'group': node}
                )
            elif type(node) is gitlab.v4.objects.User:
                # Users API does not return a creation time
                return Entity(
                    EntityType.USER,
                    path,
                    create_directory_attributes(self.initTime),
                    {'user': node}
                )
            elif type(node) is gitlab.v4.objects.Project:
                projectTime = iso8601.parse_date(node.last_activity_at).timestamp()

                return Entity(
                    EntityType.PROJECT,
                    path,
                    create_directory_attributes(projectTime),
                    {'project': node}
                )
            else:
                return None
        except KeyError:
            return None

    def resolve_project_prefix(self, path):
        """Try to resolve a path as something within a project.

        Args:
            path (str): Path into the file system.

        Returns:
            Tuple with the project object and the path relative to that project,
            or None.

        """

        for nodePath, node in self.cache.get_tree(self.userProjects).items():
            if type(node) is gitlab.v4.objects.Project and path.startswith(nodePath):
                remainingPath = pathlib.Path(path).relative_to(pathlib.Path(nodePath))
                return node, remainingPath

        return None, None

    def resolve_ref_prefix(self, path):
        """Try to resolve a path as something within a ref of a project.

        Args:
            path (str): Path into the file system.

        Returns:
            Tuple with the project object, ref object and a path relative to
            that project ref, or None.

        """

        project, remainingPath = self.resolve_project_prefix(path)
        if not project:
            return None, None, None

        for ref in self.cache.list_project_refs(project, self.tagRefs):
            try:
                treePath = remainingPath.relative_to(pathlib.Path(ref.name))
                return project, ref, treePath
            except ValueError:
                continue

        return None, None, None

    def resolve_partial_ref_prefix(self, path):
        """Try to resolve a path as a level within a hierarchical ref.

        Hierarchical refs are refs with path separators in the name, e.g.
        "feature/abc". These are represented as subdirectories.

        Args:
            path (str): Path into the file system.

        Returns:
            Tuple with the project object, the most recent matching ref object
            and the matched prefix, or None.

        """

        project, remainingPath = self.resolve_project_prefix(path)
        if not project:
            return None, None, None

        refPrefix = remainingPath.as_posix() + '/'

        # Resolve to most recently created reference for accurate directory dates
        refs = self.cache.list_project_refs(project, self.tagRefs)
        refs = sorted(refs, key=lambda ref: -iso8601.parse_date(ref.commit['committed_date']).timestamp())

        for ref in refs:
            if ref.name.startswith(refPrefix):
                return project, ref, refPrefix

        return None, None, None

    def resolve_ref(self, path):
        """Try to resolve a path as the root of a ref.

        Args:
            path (str): Path into the file system.

        """

        project, ref, remainingPath = self.resolve_ref_prefix(path)
        if not ref or remainingPath.as_posix() != '.':
            return None

        refTime = iso8601.parse_date(ref.commit['committed_date']).timestamp()

        return Entity(
            EntityType.REPOSITORY_DIR,
            path,
            create_directory_attributes(refTime),
            {'project': project, 'ref': ref}
        )

    def resolve_ref_hierarchy(self, path):
        """Try to resolve a path as a level within a hierarchical ref.

        Args:
            path (str): Path into the file system.

        """

        project, ref, refPrefix = self.resolve_partial_ref_prefix(path)
        if not ref:
            return None

        refTime = iso8601.parse_date(ref.commit['committed_date']).timestamp()

        return Entity(
            EntityType.REF_LEVEL,
            path,
            create_directory_attributes(refTime),
            {'project': project, 'ref': ref, 'refPrefix': refPrefix}
        )

    def get_entry_properties(self, project, ref, path):
        """Look up the metadata of a file or directory within a repository.

        Note:
            Listing all entries in the parent directory is the most
            straightforward way to retrieve metadata from the GitLab API.
            Especially since there aren't any specific endpoints for looking up
            non-file objects like directories.

        Args:
            project (gitlab.v4.objects.Project): Project.
            ref (gitlab.v4.objects.ProjectBranch/ProjectTag): Ref in project.
            path (str): Path within a repository tree.

        """

        parentDir = os.path.dirname(path)
        targetEntry = os.path.basename(path)

        for entry in self.cache.get_repository_tree(project, ref, parentDir):
            if entry['name'] == targetEntry:
                return entry

    def resolve_repository_entry(self, path):
        """Try to resolve a path as a file or directory within a repository.

        Args:
            path (str): Path into the file system.

        """

        project, ref, remainingPath = self.resolve_ref_prefix(path)
        if not ref or remainingPath.as_posix() == '.':
            return None

        # List parent directory to retrieve entry attributes
        entry = self.get_entry_properties(project, ref, remainingPath.as_posix())

        # Approximate entry age by last commit to containing ref
        refTime = iso8601.parse_date(ref.commit['committed_date']).timestamp()

        if entry != None:
            if entry['type'] == 'blob':
                fileSize = self.cache.get_file_size(project, ref, remainingPath.as_posix())

                # Approximate file age more accurately by its last commit timestamp
                if self.commitTimes:
                    entryTime = self.cache.get_file_commit_timestamp(project, ref, remainingPath.as_posix())
                else:
                    entryTime = refTime

                # Convert mode and strip write bits
                permissions = int(entry['mode'][-3:], 8) & 0o555

                return Entity(
                    EntityType.REPOSITORY_FILE,
                    path,
                    create_file_attributes(permissions, entryTime, fileSize),
                    {'project': project, 'ref': ref, 'file': entry}
                )
            elif entry['type'] == 'tree':
                return Entity(
                    EntityType.REPOSITORY_DIR,
                    path,
                    create_directory_attributes(refTime),
                    {'project': project, 'ref': ref, 'directory': entry}
                )

        return None

    def resolve_path(self, path):
        """Try to resolve path within the file system to an entity in GitLab.

        Possible entities are the GitLab root, a user, a group, a project, a
        ref, a level within a hierarchical ref, a file/directory within a
        repository.

        Args:
            path (str): Path into the file system.

        """

        return (
            self.resolve_root(path) or
            self.resolve_tree(path) or
            self.resolve_ref(path) or
            self.resolve_ref_hierarchy(path) or
            self.resolve_repository_entry(path)
        )

    def list_group_members(self, entity):
        """List the contents of the GitLab root or a group.

        Args:
            entity (Entity): Entity of type ROOT, GROUP or USER.

        Returns:
            List of names of the members.

        """

        members = []

        for nodePath, node in self.cache.get_tree(self.userProjects).items():
            if nodePath.startswith(entity.path):
                # Check if node is a direct child
                distance = len(pathlib.Path(nodePath).relative_to(pathlib.Path(entity.path)).parts)

                if distance == 1:
                    if type(node) is gitlab.v4.objects.Group or type(node) is gitlab.v4.objects.Project:
                        members.append(node.path)
                    elif type(node) is gitlab.v4.objects.User:
                        members.append(node.username)

        return members

    def list_project_refs(self, entity):
        """List the first level of refs of a project.

        If the project contains hierarchical refs then only the first level
        of those is returned.

        For example, a repository containing the branches "master",
        "feature/abc" and "feature/def" will have this function return the list
        ["master", "feature"].

        Args:
            entity (Entity): Entity of type PROJECT.

        Returns:
            List of (partial) names of refs.

        """

        refs = []

        for ref in self.cache.list_project_refs(entity.objects['project'], self.tagRefs):
            # If ref name is hierarchical then only return first level
            if '/' in ref.name:
                refs.append(ref.name.split('/')[0])
            else:
                refs.append(ref.name)

        # Refs may contain duplicates if the same prefix occurs multiple times
        return list(set(refs))

    def list_project_ref_hierarchy(self, entity):
        """List next level in a ref hierarchy.

        For example, if the repository has the branches "feature/abc" and
        "feature/foo/bar" and the entity represents the hierarchy "feature",
        then this function will return the list ["abc", "foo"].

        Args:
            entity (Entity): Entity of type REF_LEVEL.

        Returns:
            List of (partial) remaining names of refs.

        """

        refs = []

        for ref in self.cache.list_project_refs(entity.objects['project'], self.tagRefs):
            if ref.name.startswith(entity.objects['refPrefix']):
                remainingRefName = pathlib.Path(ref.name).relative_to(pathlib.Path(entity.objects['refPrefix'])).parts[0]
                refs.append(remainingRefName)

        return refs

    def list_repository_directory(self, entity):
        """List the files and directories in a repository subdirectory.

        Args:
            entity (Entity): Entity of type REPOSITORY_DIR.

        Returns:
            List of file and directory names.

        """

        members = []

        # There is no directory object if this is the repository root
        path = ''
        if 'directory' in entity.objects:
            path = entity.objects['directory']['path']

        for entry in self.cache.get_repository_tree(entity.objects['project'], entity.objects['ref'], path):
            if entry['type'] in ('blob', 'tree'):
                members.append(entry['name'])

        return members

    def list_members(self, entity):
        """List the files and directories contained within an entity.

        Args:
            entity (Entity): Entity of any type except for REPOSITORY_FILE.

        Returns:
            List of file and directory names contained within.

        """

        if entity.type in (EntityType.ROOT, EntityType.GROUP, EntityType.USER):
            return self.list_group_members(entity)
        elif entity.type == EntityType.PROJECT:
            return self.list_project_refs(entity)
        elif entity.type == EntityType.REF_LEVEL:
            return self.list_project_ref_hierarchy(entity)
        elif entity.type == EntityType.REPOSITORY_DIR:
            return self.list_repository_directory(entity)
        else:
            return None

    def read_file(self, entity):
        """Read the contents of a file within a repository.

        Note:
            See `gitlabfs.Cache` for why this function does not support reading
            a specific byte range.

        Args:
            entity (Entity): Entity of type REPOSITORY_FILE.

        Returns:
            Byte string of all file contents.

        """

        return self.cache.read_file(
            entity.objects['project'],
            entity.objects['ref'],
            entity.objects['file']['path']
        )