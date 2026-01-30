# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import os
import sys

from setuptools import setup, find_packages

with open('README.md') as f:
    _readme = f.read()

_mydir = os.path.abspath(os.path.dirname(sys.argv[0]))
_requires = [r for r in open(os.path.sep.join((_mydir, 'requirements.txt')), "r").read().split('\n') if len(r) > 1]
setup(
    name='kompos',
    version='0.9.4',
    description='Kompos - cloud infrastructure automation',
    long_description=_readme + '\n\n',
    long_description_content_type='text/markdown',
    url='https://github.com/adobe/kompos',
    python_requires='>=3.11',
    author='Adobe',
    author_email='noreply@adobe.com',
    license='Apache2',
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'Environment :: Console',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'License :: OSI Approved :: Apache Software License',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.11',
        'Programming Language :: Python :: 3.12',
        'Programming Language :: Python :: Implementation :: CPython',
        'Topic :: Software Development :: Build Tools',
        'Topic :: System :: Systems Administration',
        'Topic :: Utilities',
    ],
    package_dir={'': 'src'},
    packages=find_packages('src'),
    package_data={
        '': ['data/config_schema.json']
    },
    install_requires=_requires,
    entry_points={
        'console_scripts': [
            'kompos = kompos.main:run'
        ]
    }
)
