"""PyInstaller entry point for the standalone single-file binary."""
import sys

from netdoctor.cli import main

if __name__ == "__main__":
    sys.exit(main())
