"""Windows launcher: double-click to open Koobs without a console window.

(.pyw files run with pythonw.exe. On Linux/macOS use ./run.sh instead.)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "app"))

from ui import main  # noqa: E402

main()
