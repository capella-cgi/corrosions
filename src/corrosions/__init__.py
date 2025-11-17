#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Third party imports
from importlib.metadata import version
from .cips import CIPS
from .pcm import PCM
from .sync import Sync
from .acvg_dcvg import AcvgDcvg

__version__ = version("corrosions")
__author__ = "Martanto"
__author_email__ = "martanto@live.com"
__license__ = "MIT"
__copyright__ = "Copyright (c) 2025, Martanto"
__url__ = "https://github.com/martanto/corrosions"

__all__ = [
    "__version__",
    "__author__",
    "__author_email__",
    "__license__",
    "__copyright__",
    "AcvgDcvg",
    "CIPS",
    "PCM",
    "Sync",
]
