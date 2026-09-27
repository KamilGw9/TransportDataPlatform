import argparse
from importlib.metadata import version


def main() -> None:
    """Parse command-line arguments and display application information."""
    parser = argparse.ArgumentParser(
        prog="mobility",
        description="Collect and process urban transport data.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {version('mobility')}",
    )
    parser.parse_args()
    parser.print_help()
