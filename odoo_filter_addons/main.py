#!/usr/bin/env python3

import os
import sys
from string import Template
from io import StringIO
from fnmatch import fnmatch
from pathlib import Path
from tempfile import mkdtemp
from shutil import rmtree
from contextlib import contextmanager

import yaml
import click
from dotenv import dotenv_values
from plumbum import TF
from plumbum.cmd import git
from plumbum.commands.processes import ProcessExecutionError
from git_aggregator.main import main as gitaggregate

from .version import __version__

#####################################################################

class UserException(Exception):
    pass

def print_header(msg, sym):
    print(f"{sym*len(msg)}\n{msg}")

def load_yml(path, expand=False):
    if path.with_suffix(".yml").is_file():
        path = path.with_suffix(".yml")
    elif path.with_suffix(".yaml").is_file():
        path = path.with_suffix(".yaml")
    else:
        raise UserException(f"YAML file {path}.y[a]ml not found")

    with open(path, "r") as f:
        if expand and path.with_suffix(".env").is_file():
            env = dotenv_values(path.with_suffix(".env"))
            templated = Template(f.read()).substitute(env)
            yml = yaml.safe_load(StringIO(templated).read())
        else:
            yml = yaml.safe_load(f.read())
    return yml

def dump_yml(path, yml):
    with open(path, "w") as f:
        f.write(yaml.safe_dump(yml))

# Remove targets from repositories, as they cause issues with gitaggregator>=3.0.0
# https://github.com/acsone/git-aggregator/pull/55
def remove_targets(repos):
    for repo in repos.values():
        if repo.get("target"):
            del repo["target"]
    return repos

# Update remote URLs to use GitLab access token
def update_remotes(repos):
    try:
        token = os.environ["CI_JOB_TOKEN"]
        host = os.environ["CI_SERVER_HOST"]
    except KeyError as e:
        raise UserException(f"Unset environment variable {e}")
    gitlab_url = f"https://gitlab-ci-token:{token}@{host}/{{}}"
    for repo in repos.values():
        for name, url in repo["remotes"].items():
            if "git@gitlab.com:" in url:
                project = url.split(":")[1]
                repo["remotes"][name] = gitlab_url.format(project)
    return repos

#####################################################################

def is_module(path):
    path = Path(path)
    return path.is_dir() and (path/"__manifest__.py").is_file()

def filter_repo(agg_path, rname, repo, modules):
    rpath = agg_path/rname
    rbranch = repo["target"].split()[1] if repo.get("target") else "_git_aggregated"
    # Fetch the specified branch from the remote repo
    if git["remote", "get-url", rname] & TF:
        git("remote", "set-url", rname, rpath)
    else:
        git("remote", "add", rname, rpath)
    git("fetch", "--depth", "1", rname, rbranch)
    # Checkout changes for each of the modules listed
    for fname in next(os.walk(rpath))[1]:
        if is_module(rpath/fname) and any([fnmatch(fname, m) for m in modules]):
            git("checkout", f"{rname}/{rbranch}", fname)
            print(f"Added module {fname}")
    # Create a message that will allow tracing the commit
    lines = [rname]
    for merge in repo["merges"]:
        merge = merge.strip()
        remote, ref = merge.split()
        if "/" in ref:
            commit = git("-C", rpath, "ls-remote", "--exit-code", remote, ref).strip().split()[0]
            lines.append(f"{merge} {commit}")
        elif len(ref) == 40:
            lines.append(merge)
        else:
            commit = git("-C", rpath, "rev-parse", merge.replace(" ", "/")).strip()
            lines.append(f"{merge} {commit}")
    message = "\n".join(lines)
    print(f"Partial message:\n{message}")
    return message

def filter_repos(output_path, agg_path, repos, addons, release, push, gitlab_ci):
    os.chdir(output_path)
    # Remove old modules
    for fname in next(os.walk("."))[1]:
        if is_module(fname):
            try:
                # Remove from index and working tree
                git("rm", "-rf", fname)
            except ProcessExecutionError:
                # Module not in index, remove from working tree
                rmtree(fname)
    # Add new modules
    messages = []
    for rname, modules in addons.items():
        print_header(f"Filtering '{rname}'", '-')
        repo = repos.get(rname) or repos.get(f"./{rname}")
        if not repo:
            raise UserException(f"addons.yml entry {rname} not found in repos.yml")
        repo_message = filter_repo(agg_path, rname, repo, modules)
        messages.append(repo_message)
    print_header("Finished filtering", '*')
    # If not in release mode remove files from the index
    if not release:
        git("rm", "-rf", "--cached", ".")
        print("Release disabled, nothing commited")
    # Otherwise, commit changes if any, and push them to remote if specified
    elif filter(None, messages) and git["diff", "--staged", "--quiet"] & TF(1):
        messages = [f"[AUTO] {__package__} {__version__}"] + messages
        message = "\n".join(messages)
        git("commit", "-m", message)
        print("Changes commited")
        if push:
            if git["rev-parse", "@{u}"] & TF:
                git("push")
            elif gitlab_ci:
                branch = os.environ.get("CI_COMMIT_BRANCH")
                if not branch:
                    raise UserException("Unset environment variable CI_COMMIT_BRANCH")
                git("push", "origin", f"HEAD:{branch}")
            else:
                raise UserException("addons.yml entry {} not found in repos.yml".format(rname))
            print("Commit pushed to remote")
    else:
        print("No changes, nothing commited")

@contextmanager
def set_argv(new_argv):
    old_argv = sys.argv
    sys.argv = new_argv
    try:
        yield
    finally:
        sys.argv = old_argv

# Create a git repo if not present and aggregate addon repositories
def initialize_repos(output_path, agg_path, repos):
    if not output_path.is_dir():
        print(f"Initializing git repository in '{output_path}'")
        output_path.mkdir(parents=True, exist_ok=True)
    git("-C", output_path, "init")

    os.chdir(agg_path)
    dump_yml("repos.yml", repos)

    new_argv = ["gitaggregate", "-c", "repos.yml"]
    with set_argv(new_argv):
        gitaggregate()
    print(f"gitaggregate output written to '{agg_path}'")

#####################################################################

# API entry point
def api_main(input_path=None, output_path=None, clean=True, cache=False, release=False, push=False, gitlab_ci=False):
    input_path = Path(input_path).resolve() if input_path else Path.cwd()
    output_path = Path(output_path).resolve() if output_path else Path.cwd()
    if cache:
        clean = False
        agg_path = Path.home()/".cache"/"odoo-filter-addons"
        agg_path.mkdir(parents=True, exist_ok=True)
    else:
        agg_path = Path(mkdtemp())

    print(f"Loading configuration files from '{input_path}'")
    repos = load_yml(input_path/"repos", True)
    addons = load_yml(input_path/"addons")

    repos = remove_targets(repos)
    if gitlab_ci:
        repos = update_remotes(repos)

    try:
        print(f"Filtering addons to '{output_path}'")
        initialize_repos(output_path, agg_path, repos)
        filter_repos(output_path, agg_path, repos, addons, release, push, gitlab_ci)
    except Exception as e:
        if clean:
            rmtree(agg_path)
        raise e
    if clean:
        print("Cleaning up intermediate output")
        rmtree(agg_path)

# CLI entry point
@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.version_option()
@click.option("-i", "--input-path", help="Path to directory containing configuration files.")
@click.option("-o", "--output-path", help="Path to the directory that will contain the output.")
@click.option("-c", "--clean/--no-clean", is_flag=True, default=True, help="Clean gitaggregate output.")
@click.option("-C", "--cache/--no-cache", is_flag=True, default=False, help="Cache gitaggregate output, overrides -c.")
@click.option("-r", "--release/--no-release", is_flag=True, default=False, help="Create a relase commit if any changes are made.")
@click.option("-p", "--push/--no-push", is_flag=True, default=False, help="Push to remote repo if any changes are commited.")
@click.option("-g", "--gitlab-ci", is_flag=True, default=False, help="Update client addon repository in GitLab CI.")
def cli_main(input_path, output_path, clean, cache, release, push, gitlab_ci):
    import sys
    import traceback
    try:
        api_main(input_path, output_path, clean, cache, release, push, gitlab_ci)
        sys.exit(0)
    except UserException as e:
        print("User error:", e)
    except yaml.YAMLError as e:
        print("Invalid YAML content:", e)
    except ProcessExecutionError as e:
        print("Process execution error:", e)
    except Exception as e:
        print(traceback.format_exc())
    sys.exit(1)

#####################################################################

if __name__ == "__main__":
    cli_main()
