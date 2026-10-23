import sys

from .resources import resource_path

if resource_path("") not in sys.path:
    sys.path.insert(0, resource_path(""))
