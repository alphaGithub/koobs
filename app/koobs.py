#!/usr/bin/env python3
"""Koobs - tag and browse the books in All/.  Run: python3 app/koobs.py"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ui import main  # noqa: E402

if __name__ == "__main__":
    main()
