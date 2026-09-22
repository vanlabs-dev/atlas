#!/usr/bin/env python3
"""Retired spec-sync publication entrypoint; never bypass maintenance gates."""
import sys


def main() -> int:
    sys.stderr.write(
        'Spec-sync publisher retired. Use the guarded maintenance controller '
        'with its explicit operator runtime config. Publication requires '
        'evidence, isolated tests, independent review, and a signed receipt.\n'
    )
    return 2


if __name__ == '__main__':
    sys.exit(main())
