import importlib

import pytest
from streamlit.testing.v1 import AppTest

from plugai_trade.app.registry import SCREENS


@pytest.mark.parametrize("module", ["home"] + [s[2] for s in SCREENS])
def test_page_renders(module):
    code = f"from plugai_trade.app.pages import {module} as m\nm.render()\n"
    at = AppTest.from_string(code, default_timeout=60)
    at.run()
    assert not at.exception, [e.value for e in at.exception]
