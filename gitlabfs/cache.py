# -*- coding: utf-8 -*-
"""Caching of GitLab API responses.

The purpose of this module is to create a caching layer around the GitLab API to
facilitate responsive access. This is necessary because many file system access
patterns require querying the same thing again and again.

For example, GitLab does not support range requests for file contents, so the
entire contents should be cached to handle chunk-by-chunk reading efficiently.

Another example is the requirement to resolve paths to specific users, groups
and projects where it is beneficial to cache the entire tree for fast lookups.

The trade-off of course is that the file system is not a completely up-to-date
view of the contents of GitLab. To ensure that the view is eventually consistent
the cache is set up to automatically expire after a number of seconds.

"""

import time
import urllib.parse

import cachetools
import iso8601

def cache_factory(cacheExpiry, expireProjectTree):
    """Create a class wrapping the GitLab API with a cache.

    Note:
        The purpose of this factory function is to instantiate the caching
        decorators with different parameters.

    Args:
        cacheExpiry (int): Number of seconds until the cache expires.
        expireProjectTree (bool): Enable cache expiry for the project tree.

    """

    if expireProjectTree:
        treeCache = cachetools.TTLCache(1, cacheExpiry)
    else:
        # Effectively disables cache expiry
        treeCache = cachetools.LRUCache(1)

    class Cache:
        """Class that exposes GitLab API functions with cached responses.

        Attributes:
            api (gitlab.Gitlab): Base API instance.

        """

        def __init__(self, api):
            """Initialize GitLab API cache.

            Args:
                api (gitlab.Gitlab): Base API instance.

            """

            self.api = api

        def prefix_count(self, obj, keyPrefix):
            """Count the number of items in a dictionary with a key prefix.

            Args:
                obj (dict): Dictionary.
                keyPrefix (str): Key prefix to search for.

            Returns:
                Number of keys in the dictionary starting with the key prefix.

            """

            return len(list(filter(lambda k: k.startswith(keyPrefix), obj.keys())))

        @cachetools.cached(treeCache)
        def get_tree(self, userProjects):
            """Get a dictionary with all users, groups and projects by path.

            Args:
                userProjects (bool): Include users and their projects.

            Note:
                The dictionary contains a special member 'time' that indicates
                the age of the (cached) response. All other members start with
                a path separator (/).

            """

            tree = {}

            # Add projects to tree
            projects = self.api.projects.list(all=True)

            for project in projects:
                tree['/' + project.path_with_namespace] = project

            # Add groups and subgroups to tree
            groups = self.api.groups.list(all=True)

            for group in groups:
                # Check if there are projects within the group
                if self.prefix_count(tree, '/' + group.full_path) > 0:
                    tree['/' + group.full_path] = group

            # Add users to tree
            if userProjects:
                users = self.api.users.list(all=True)

                for user in users:
                    # Check if there are projects for this user
                    if self.prefix_count(tree, '/' + user.username) > 0:
                        tree['/' + user.username] = user

            tree['time'] = time.time()

            return tree

        @cachetools.cached(cachetools.TTLCache(128, cacheExpiry))
        def list_project_refs(self, project, includeTags):
            """List all refs (branches and tags) in a project.

            Args:
                project (gitlab.v4.objects.Project): The project.
                includeTags (bool): Include tags in the refs.

            """

            refs = project.branches.list(all=True)

            if includeTags:
                refs += project.tags.list(all=True)

            return refs

        @cachetools.cached(cachetools.TTLCache(128, cacheExpiry))
        def get_file_metadata(self, project, ref, path):
            """Get the metadata headers of a file under a project ref.

            Note:
                See the section about HEAD requests in the GitLab documentation:
                https://docs.gitlab.com/ee/api/repository_files.html#get-file-from-repository

            Args:
                project (gitlab.v4.objects.Project): The project.
                ref (gitlab.v4.objects.ProjectBranch/ProjectTag): A branch or tag.
                path (str): Path to a file in the repository.

            """

            # URL encode everything in a path including path separators (/)
            safePath = urllib.parse.quote(path, safe='')

            # python-gitlab library does not support metadata only file requests
            # out of the box
            response = self.api.http_request(
                'head',
                '/projects/%s/repository/files/%s' % (project.id, safePath),
                ref=ref.name
            )

            return response.headers

        def get_file_size(self, project, ref, path):
            """Get the size of a file under a project ref in bytes.

            Note:
                There is no standard way to retrieve file size with the GitLab
                library without also downloading all of the contents, so we use
                a metadata request instead.

                Not cached since it can fully rely on the metadata cache.

            Args:
                project (gitlab.v4.objects.Project): The project.
                ref (gitlab.v4.objects.ProjectBranch/ProjectTag): A branch or tag.
                path (str): Path to a file in the repository.

            """

            metadata = self.get_file_metadata(project, ref, path)
            return int(metadata['X-Gitlab-Size'])

        @cachetools.cached(cachetools.TTLCache(128, cacheExpiry))
        def get_file_commit_timestamp(self, project, ref, path):
            """Get the timestamp of the commit that last affected a given file.

            Note:
                There is currently no way to directly retrieve the last modified
                timestamp of a file in a repository, so the commit timestamp can
                be used to approximate it.

            Args:
                project (gitlab.v4.objects.Project): The project.
                ref (gitlab.v4.objects.ProjectBranch/ProjectTag): A branch or tag.
                path (str): Path to a file in the repository.

            """

            metadata = self.get_file_metadata(project, ref, path)
            commitHash = metadata['X-Gitlab-Last-Commit-Id']

            commitTime = project.commits.get(commitHash).created_at

            return iso8601.parse_date(commitTime).timestamp()

        @cachetools.cached(cachetools.TTLCache(128, cacheExpiry))
        def get_repository_tree(self, project, ref, path):
            """List all entries under a path given a project ref.

            Args:
                project (gitlab.v4.objects.Project): The project.
                ref (gitlab.v4.objects.ProjectBranch/ProjectTag): A branch or tag.
                path (str): Path to a directory in the repository.

            """

            return project.repository_tree(path=path, ref=ref.name)

        @cachetools.cached(cachetools.TTLCache(128, cacheExpiry))
        def read_file(self, project, ref, path):
            """Read all contents of the specified file.

            Note:
                The GitLab API does not support HTTP range requests, so we can
                only download the entire file. Caching takes care of the pattern
                where this function is invoked many times to read a file chunk
                by chunk.

            Args:
                project (gitlab.v4.objects.Project): The project.
                ref (gitlab.v4.objects.ProjectBranch/ProjectTag): A branch or tag.
                path (str): Path to a file in the repository.

            """

            return project.files.get(file_path=path, ref=ref.name).decode()

    return Cache