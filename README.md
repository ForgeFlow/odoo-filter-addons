# Odoo filter addons

Simple command line utility used to filter specific odoo addons from
multiple repositories. It leverages [git-aggregator](https://github.com/acsone/git-aggregator)
and its **repo.yml** format as well as [doodba](https://github.com/Tecnativa/doodba)'s
addons **addons.yml** format.

# Installation

- Via `pipx` with `pipx install odoo-filter-addons`
- Via `pip` with `python3 -m pip install odoo-filter-addons`
- After cloning locally with `python3 -m pip install .`

# Usage

In order to work, the program requires a folder containing the configuration files
[`repos.yml`](https://github.com/acsone/git-aggregator#configuration-file) and
[`addons.yml`](https://github.com/Tecnativa/doodba#optodoocustomsrcaddonsyaml),
and if `repos.yml` references environment variables they can be defiend in `repos.env`.
If the files are valid, the modules specified in `addons.yml` are filtered from the
results of running `gitaggregate` into the specified output directory.

By default, both the input and output path default to the current working directory,
but can be overridden through the `-i/--input-path` and `-o/--output-path` flags
respectively. Additionally, some other flags can be provided to alter the behavior of
the program:

| Flag                      | Default | Description                                               |
|---------------------------|---------|-----------------------------------------------------------|
| -c, --clean / --no-clean  | True    | Clean intermediate output                                 |
| -p, --push / --no-push    | False   | Push to remote repo if any changes are commited           |
| -g, --gitlab-ci           | False   | Update client addon repository in GitLab CI               |
