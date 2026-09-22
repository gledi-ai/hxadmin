from importlib.metadata import version

from hxadmin.admin import HxAdmin
from hxadmin.views import ModelView

__version__ = version("hxadmin")

__all__ = ["HxAdmin", "ModelView", "__version__"]
