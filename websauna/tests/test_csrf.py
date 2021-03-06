"""Test CSRF functionality as functional tests."""
import pytest

from pyramid import testing
from pyramid.config.views import DefaultViewMapper
from pyramid.exceptions import BadCSRFToken
from pyramid.testing import DummySession
from websauna.system.core.csrf import csrf_mapper_factory
from webtest import TestApp

from . import csrfsamples


@pytest.fixture()
def csrf_app(request):
    """py.test fixture to set up a dummy app for CSRF testing.

    :param request: pytest's FixtureRequest (internal class, cannot be hinted on a signature)
    """

    session = DummySession()

    config = testing.setUp()
    config.set_view_mapper(csrf_mapper_factory(DefaultViewMapper))
    config.add_route("home", "/")
    config.add_route("csrf_sample", "/csrf_sample")
    config.add_route("csrf_exempt_sample", "/csrf_exempt_sample")
    config.add_route("csrf_exempt_sample_context", "/csrf_exempt_sample_context")
    config.scan(csrfsamples)

    # We need sessions in order to use CSRF feature

    def dummy_session_factory(secret):
        # Return the same session over and over again
        return session

    config.set_session_factory(dummy_session_factory)

    def teardown():
        testing.tearDown()

    app = TestApp(config.make_wsgi_app())
    # Expose session data for tests to read
    app.session = session
    return app


@pytest.fixture()
def session(request, csrf_app):
    return csrf_app.session


def test_csrf_by_default(csrf_app: TestApp, session: DummySession):
    """CSRF goes throgh if we have a proper token."""

    resp = csrf_app.post("/csrf_sample", {"csrf_token": session.get_csrf_token()})
    assert resp.status_code == 200


def test_csrf_by_default_fail(csrf_app: TestApp, session: DummySession):
    """CSRF error is raised by default if we try to POST to a view and we don't have token."""

    with pytest.raises(BadCSRFToken):
        csrf_app.post("/csrf_sample")


def test_csrf_exempt(csrf_app: TestApp, session: DummySession):
    """Decorated views don't have automatic CSRF check."""

    resp = csrf_app.post("/csrf_exempt_sample")
    assert resp.status_code == 200

    resp = csrf_app.post("/csrf_exempt_sample_context")
    assert resp.status_code == 200
