# Odoo filter addons

Simple command line utility used to filter specific odoo addons from
multiple repositories. It leverages [git-aggregator](https://github.com/acsone/git-aggregator)
and its **repo.yml** format as well as [doodba](https://github.com/Tecnativa/doodba)'s
addons **addons.yml** format.

# Installation

- Via `pipx` with `pipx install odoo-filter-addons` (recommended)
- Via `pip` with `python3 -m pip install odoo-filter-addons`
- After cloning locally with `python3 -m pip install .`

# Usage

To execute the program simply run `odoo_filter_addons`. In order to work, it requires a directory
containing the configuration files [`repos.yml`](https://github.com/acsone/git-aggregator#configuration-file)
and [`addons.yml`](https://github.com/Tecnativa/doodba#optodoocustomsrcaddonsyaml). If `repos.yml`
references any [environment variables](https://www.dotenv.org/docs/security/env.html), they can
be defined in `repos.env`. If the files are valid, the modules specified in `addons.yml` are
filtered from the results of running `gitaggregate` into the specified output directory.

By default, both the input and output path default to the current working directory,
but can be overridden through the `-i/--input-path` and `-o/--output-path` flags
respectively. Additionally, some other flags can be provided to alter the behavior of
the program:

| Flag                          | Default | Description                                               |
|-------------------------------|---------|-----------------------------------------------------------|
| -i, --input-path              | "."     | Path to directory containing configuration files          |
| -o, --output-path             | "."     | Path to the directory that will contain the output        |
| -c, --clean / --no-clean      | True    | Clean gitaggregate output                                 |
| -C, --cache / --no-cache      | False   | Cache gitaggregate output, overrides -c                   |
| -r, --release / --no-release  | False   | Create a release commit if any changes are made           |
| -p, --push / --no-push        | False   | Push to remote repo if any changes are commited           |
| -g, --gitlab-ci               | False   | Update client addon repository in GitLab CI               |
