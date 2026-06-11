# FinCenter plugin entry point for AstrBot
import os
import sys

# AstrBot extracts plugins to data/plugins/<name>/ — ensure the plugin root is on sys.path
_plugin_dir = os.path.dirname(os.path.abspath(__file__))
if _plugin_dir not in sys.path:
    sys.path.insert(0, _plugin_dir)

from src.main import FinCenterPlugin
