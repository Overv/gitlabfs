import setuptools

with open('README.md', 'r') as f:
    long_description = f.read()

setuptools.setup(
    name='gitlabfs',
    version='1.0.4',
    scripts=['glfs'] ,
    author="Alexander Overvoorde",
    author_email="overv161@gmail.com",
    description="Mount projects in GitLab as a file system",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/Overv/gitlabfs",
    packages=['gitlabfs'],
    classifiers=[
        "Programming Language :: Python :: 3.5",
        "License :: OSI Approved :: MIT License",
        "Operating System :: POSIX :: Linux",
    ],
    install_requires=[
        'python-gitlab',
        'fusepy',
        'iso8601',
        'cachetools'
    ],
    python_requires='>=3.5'
)