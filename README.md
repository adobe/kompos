# kompos
[![Build Status](https://www.travis-ci.com/adobe/kompos.svg?token=8uHqfhgsxdvJ93qWAxhn&branch=master)](https://www.travis-ci.com/adobe/kompos) [![Docker pull](https://img.shields.io/docker/pulls/adobe/kompos)](https://hub.docker.com/r/adobe/kompos) [![](https://images.microbadger.com/badges/version/adobe/kompos.svg)](https://microbadger.com/images/adobe/kompos "Get your own version badge on microbadger.com") [![License](https://img.shields.io/github/license/adobe/kompos)](https://github.com/adobe/kompos/blob/master/LICENSE)

![kompos](img/knot.png)

**Kompos** is a configuration driven tool for provisioning and managing Kubernetes infrastructure across AWS and Azure.
It uses a hierarchical folder structure and yaml files to store and generate configurations, with pluggable compositions that encapsulates the infrastructure code and state. Terraform and helmfile are supported as provisioners.

* [Hierarchical](#hierarchical)
* [Installing](#installing)
   * [Locally](#locally)
   * [Nix versioning](#nix-versioning)
   * [Docker image](#docker-image)
* [License](#license)


# Hierarchical configuration
See examples/features/hierarchical

# Installing

### Locally
```sh
pip3 install virtualenv
# Make sure pip is up to date
curl https://bootstrap.pypa.io/get-pip.py | python3

# Install virtualenv
pip3 install --upgrade virtualenv
pip3 install --upgrade virtualenvwrapper

echo 'export WORKON_HOME=$HOME/.virtualenvs' >> ~/.bash_profile
echo 'source /usr/local/bin/virtualenvwrapper.sh' >> ~/.bash_profile
source ~/.bash_profile

# create virtualenv
mkvirtualenv kompos
workon kompos

# uninstall previous `kompos` version (if you have it)
pip3 uninstall kompos --yes

# install kompos stable release
pip3 install --upgrade kompos
```


### Nix versioning
```
curl https://nixos.org/nix/install | sh
```

### Docker Image


## License
[Apache License 2.0](/LICENSE)
