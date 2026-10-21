#!/usr/bin/env python3
"""Compatibility launcher for the single supported CenterStage service."""
import sys
from centerstage.cli import main

if __name__ == '__main__':
    sys.argv.insert(1, 'serve')
    main()
