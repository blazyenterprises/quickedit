"""Let Python 3.14's zipfs-based Tcl/Tk find its embedded standard library."""

import os


os.environ.pop("TCL_LIBRARY", None)
os.environ.pop("TK_LIBRARY", None)
