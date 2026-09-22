from importlib.metadata import version

from hxadmin.actions import ActionResult, action
from hxadmin.admin import HxAdmin
from hxadmin.fields import Field, RelationField
from hxadmin.forms import FormError
from hxadmin.pages import Page
from hxadmin.views import ModelView

__version__ = version("hxadmin")
__all__ = [
    "ActionResult",
    "Field",
    "FormError",
    "HxAdmin",
    "ModelView",
    "Page",
    "RelationField",
    "__version__",
    "action",
]
