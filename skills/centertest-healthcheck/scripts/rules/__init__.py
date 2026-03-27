"""
Auto-import all rule_*.py modules to trigger @rule decorator registration.

This package mirrors Eir's Spring component scanning for @RuleClass beans.
"""

import importlib
import os
import pkgutil

# Auto-discover and import all rule_*.py modules in this directory
_package_dir = os.path.dirname(__file__)
for _importer, _modname, _ispkg in pkgutil.iter_modules([_package_dir]):
    if _modname.startswith("rule_"):
        importlib.import_module(f".{_modname}", __package__)
