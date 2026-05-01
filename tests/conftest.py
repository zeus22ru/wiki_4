"""Общие pytest fixtures."""

import pytest


@pytest.fixture
def client():
    from web_app import app

    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
