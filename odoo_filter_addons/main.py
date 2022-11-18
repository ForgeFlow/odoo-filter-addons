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

#####################################################################

class UserException(Exception):
    pass

def print_header(msg, sym):
    print("{}\n{}".format(sym*len(msg), msg))

def load_yml(path, expand=False):
    if path.with_suffix(".yml").is_file():
        path = path.with_suffix(".yml")
        suffix = ".yml"
    elif path.with_suffix(".yaml").is_file():
        path = path.with_suffix(".yaml")
        suffix = ".yaml"
    else:
        raise UserException("YAML file {}.y[a]ml not found".format(path))

    with open(path, "r") as f:
        if expand and path.with_suffix(".env").is_file():
            env = dotenv_values(path.with_suffix(".env"))
            templated = Template(f.read()).substitute(env)
            yml = yaml.safe_load(StringIO(templated).read())
        else:
            yml = yaml.safe_load(f.read())
    return yml, suffix

def dump_yml(path, yml):
    with open(path, "w") as f:
        f.write(yaml.safe_dump(yml))

#####################################################################

def is_module(path):
    path = Path(path)
    return path.is_dir() and (path/"__manifest__.py").is_file()

def filter_repo(tmp_path, rname, repo, modules):
    rpath = tmp_path/rname
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
            git("checkout", "{}/{}".format(rname, rbranch), fname)
            print("Added module {}".format(fname))
    # Create a message that will allow tracing the commit
    lines = [rname]
    for merge in repo["merges"]:
        if "merge-requests" in merge or "pull" in merge:
            last_hash = git("-C", rpath, "ls-remote", "--exit-code", *merge.split()).split()[0]
        else:
            last_hash = git("-C", rpath, "rev-parse", merge.replace(" ", "/"))
        lines.append("{} {}".format(merge, last_hash).strip())
    message = "\n".join(lines)
    print("Partial message:\n{}".format(message))
    return message

def filter_repos(output_path, tmp_path, repos, addons, push, gitlab_ci):
    os.chdir(output_path)
    # Remove old modules
    for fname in next(os.walk("."))[1]:
        if is_module(fname):
            git("rm", "-rf", fname)
    # Add new modules
    messages = []
    for rname, modules in addons.items():
        print_header("Filtering '{}'".format(rname), '-')
        repo = repos.get(rname) or repos.get("./{}".format(rname))
        if not repo:
            raise UserException("addons.yml entry {} not found in repos.yml".format(rname))
        repo_message = filter_repo(tmp_path, rname, repo, modules)
        messages.append(repo_message)
    print_header("Finished filtering", '*')
    # Commit changes, if any, and push them to remote if specified
    message = "\n".join(filter(None, messages))
    if message and git["diff", "--staged", "--quiet"] & TF(1):
        git("commit", "-m", message)
        print("Changes commited")
        if push:
            if git["rev-parse", "@{u}"] & TF:
                git("push")
            elif gitlab_ci:
                branch = os.environ.get("CI_COMMIT_BRANCH")
                if not branch:
                    raise UserException("Unset environment variable CI_COMMIT_BRANCH")
                git("push", "origin", "HEAD:{}".format(branch))
            else:
                raise UserException("addons.yml entry {} not found in repos.yml".format(rname))
            print("Commit pushed to remote")
    else:
        print("No changes, nothing commited")

# Update remote URLs to use GitLab access token
def update_ci_urls(repos):
    try:
        token = os.environ["CI_JOB_TOKEN"]
        host = os.environ["CI_SERVER_HOST"]
    except KeyError as e:
        raise UserException("Unset environment variable {}".format(e))
    gitlab_url = "https://gitlab-ci-token:{}@{}/{{}}".format(token, host)
    for repo in repos.values():
        for name, url in repo["remotes"].items():
            if "git@gitlab.com:" in url:
                project = url.split(":")[1]
                repo["remotes"][name] = gitlab_url.format(project)
    return repos

@contextmanager
def set_argv(new_argv):
    old_argv = sys.argv
    sys.argv = new_argv
    try:
        yield
    finally:
        sys.argv = old_argv

# Create a git repo if not present and aggregate addon repositories
def initialize_repos(output_path, input_path, tmp_path, repos_suffix):
    os.chdir(tmp_path)
    if not output_path.is_dir():
        print("Initializing git repository in '{}'".format(output_path))
        Path(output_path).mkdir(parents=True, exist_ok=True)
    git("-C", output_path, "init")

    repos_path = (input_path/"repos").with_suffix(repos_suffix)
    new_argv = ["gitaggregate", "-c", str(repos_path)]
    if (input_path/"repos.env").is_file():
        new_argv += ["-e", "--env-file", str(input_path/"repos.env")]
    with set_argv(new_argv):
        gitaggregate()
    print("Writing gitaggregate output to '{}'".format(tmp_path))

#####################################################################

# API entry point
def main(input_path=None, output_path=None, clean=True, push=False, gitlab_ci=False):
    input_path = Path(input_path).resolve() if input_path else Path.cwd()
    output_path = Path(output_path).resolve() if output_path else Path.cwd()
    tmp_path = Path(mkdtemp())

    print("Loading configuration files from '{}'".format(input_path))
    repos, repos_suffix = load_yml(input_path/"repos", True)
    addons, addons_suffix = load_yml(input_path/"addons")
    if gitlab_ci:
        repos = update_ci_urls(repos)
        dump_yml("repos.yml", update_ci_urls(repos))

    try:
        print("Filtering addons to '{}'".format(output_path))
        initialize_repos(output_path, input_path, tmp_path, repos_suffix)
        filter_repos(output_path, tmp_path, repos, addons, push, gitlab_ci)
    except Exception as e:
        if clean:
            rmtree(tmp_path)
        raise e
    if clean:
        print("Cleaning up intermediate output")
        rmtree(tmp_path)

# CLI entry point
@click.command(context_settings=dict(help_option_names=['-h', '--help']))
@click.version_option()
@click.option("-i", "--input-path", help="Path to directory containing configuration files.")
@click.option("-o", "--output-path", help="Path to the directory that will contain the output.")
@click.option("-c", "--clean/--no-clean", is_flag=True, default=True, help="Clean intermediate output.")
@click.option("-p", "--push/--no-push", is_flag=True, default=False, help="Push to remote repo if any changes are commited.")
@click.option("-g", "--gitlab-ci", is_flag=True, default=False, help="Update client addon repository in GitLab CI.")
def cli_main(input_path, output_path, clean, push, gitlab_ci):
    import sys
    import traceback
    try:
        main(input_path, output_path, clean, push, gitlab_ci)
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
