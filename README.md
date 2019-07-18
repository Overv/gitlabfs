# gitlabfs

gitlabfs allows you to mount all projects in a company's GitLab instance as a file system.

## About

This project was conceived out of a need to easily browse code in many different repositories within a company. While GitLab does have builtin browsing and search, it's just not as convenient to use as common tools like `find` and `grep`.

It sets out to solve that by exposing an entire GitLab instance as a file system with the following hierarchy:

```
/
  /user
    /project
      /master
        README.md
      /feature
        /abc
          /src
            main.py
      /v1.0
        main.py
  /group
    /subgroup
      /project
```

This allows you to freely browse all of the code in a GitLab instance without having to clone everything. All of the files are loaded from the GitLab API as you access them. The only caveat is that it is a read-only view.

## Installation

Install the latest version of gitlabfs from [PyPI](https://pypi.org/project/gitlabfs/):

    pip install gitlabfs

## Usage

1. Go to your profile page in GitLab and [generate a new access token](https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html) with the `api` scope.
2. Create a directory where you would like to access your projects from, e.g. `~/gitlab`.
3. Mount GitLab at that directory:

    ```
    glfs https://gitlab.mycompany.com ~/gitlab
    ```

  You will be asked to provide your access token and then the GitLab hierarchy will be mounted.

## Configuration

Various options can be passed to configure the properties of the file system:

* `--tags`: Include tags in the list of repository refs.
* `--users`: List user repositories as well.
* `--file-times`: Better approximate file modification times with commit metadata.
* `--cache-expiry=SEC`: Expire the cache after this many seconds (default: 60).
* `--fresh-project-tree`: Enable cache expiry for the project tree.
* `--debug`: Enable verbose logging for development purposes.

Many of these are not enabled by default because they may result in worse performance or more clutter.

The access token must be provided via a command line prompt by default, but can also be passed via the `GITLAB_TOKEN` environment variable.

## Limitations

* Not designed for GitLab instances with a huge number of projects (e.g. gitlab.com).
* File modification times are not accurate since they are not exposed by the GitLab API.

## Development

The file system can be easily run locally with [Pipenv](https://github.com/pypa/pipenv):

```
pipenv install
pipenv run ./glfs <url> <mountpoint> [options]
```

And the PyPI package is published using the following commands:

```
pipenv run python setup.py sdist bdist bdist_wheel
pipenv run twine upload dist/*
```

## License

MIT License