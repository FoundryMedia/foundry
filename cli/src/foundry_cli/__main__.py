import sys

from foundry_cli.cli import cli
from foundry_cli.core.alias.dispatch import expand_argv

if __name__ == "__main__":
    # Allow dynamic aliases by expanding argv before Click parses it.
    sys.argv = expand_argv(sys.argv)
    cli()
