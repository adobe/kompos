# Copyright 2019 Adobe. All rights reserved.
# This file is licensed to you under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License. You may obtain a copy
# of the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software distributed under
# the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR REPRESENTATIONS
# OF ANY KIND, either express or implied. See the License for the specific language
# governing permissions and limitations under the License.

import os
import json
import tempfile
import logging
import subprocess

from distutils.dir_util import copy_tree, remove_tree
from string import Template

NIX_GIT_REPO_TEMPLATE = Template(
    """
with import <nixpkgs>{};

pkgs.stdenv.mkDerivation {
  name    = "$name";
  version = "$version";

  src = pkgs.fetchgit {
    url    = "$url";
    rev    = "$rev";
    sha256 = "$sha256";
  };

  installPhase = ''
    mkdir -p $out/src/
    cp -r * $out/src/
  '';
}
"""
)

logger = logging.getLogger(__name__)


def run_cmd(cmd):
    ret = subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, universal_newlines=True,
    )

    if ret.returncode != 0:
        print(ret.stdout)
        print(ret.stderr)
        ret.check_returncode()

    return ret


def nix_generate_git_expr(name, version, info):
    """
    Generate a nix expression to install a git repository.
    """
    return NIX_GIT_REPO_TEMPLATE.safe_substitute(
        dict(
            name=name,
            version=version,
            url=info["url"],
            rev=info["rev"],
            sha256=info["sha256"],
        )
    )


def nix_install(name, repo_url, version, sha256=None):
    """
    Install a git repo with the default nix expression.
    """
    expr = nix_generate_git_expr(
        name, version, dict(url=repo_url, rev=version, sha256=sha256)
    )

    # Use nix-prefetch-git if no valid values were given.
    if not sha256 or version == "master":
        expr = nix_generate_git_expr(name, version, git_drv_info(repo_url, version))

    logging.info("Installing nix derivation %s-%s", name, version)

    with tempfile.TemporaryDirectory() as tmpdir:
        nix_file = os.path.join(tmpdir, "main.nix")

        with open(nix_file, "wb") as tmp:
            tmp.write(expr.encode("utf-8"))

        run_cmd(["nix-env", "-f", nix_file, "-i"])


def git_drv_info(url, version):
    """
    Retrieve the necessary git info to create a nix expression using `fetchgit`.
    """
    rev = []

    if version != "master":
        rev = ["--rev", version]

    ret = run_cmd(
        ["nix-prefetch-git", "--no-deepClone", "--quiet", "--url", url,] + rev
    )

    return json.loads(ret.stdout)


def nix_out_path(name):
    """
    Retrieve the path where a derivation is installed.
    """
    ret = run_cmd(["nix-env", "--query", name, "--out-path"])

    parts = list(filter(lambda x: x, ret.stdout.split(" ")))

    if len(parts) != 2:
        raise Exception("Failed to retrieve out path for derivation {}".format(name))

    return os.path.join(parts[1].rstrip("\n\r"), "src")


def writeable_nix_out_path(name):
    """
    Copy a nix derivation to a temporary writeable directory.
    """
    out_path = nix_out_path(name)
    tmp_dir = os.path.join(tempfile.gettempdir(), name)

    logging.info("Creating writeable directory '%s'", tmp_dir)

    if os.path.exists(tmp_dir):
        remove_tree(tmp_dir)

    os.mkdir(tmp_dir)

    logging.info(
        "Copying nix derivation '%s' to a writeable location '%s'", name, tmp_dir,
    )

    copy_tree(out_path, tmp_dir)

    return tmp_dir
