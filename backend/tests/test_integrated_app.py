"""Layered launcher contract tests.

These tests intentionally import ``run:app`` rather than the upstream core app.
That catches the class of failure where the server starts successfully but the
extension endpoints used by the frontend were never mounted.
"""

from fastapi.testclient import TestClient

from run import app


EXPECTED_EXTENSION_PATHS = {
    "/reverse-geocode",
    "/route-preview",
    "/recommend/adventure",
    "/recommend/adventure/course",
    "/recommend/adventure/blind",
    "/recommend/adventure/blind/reveal",
    "/recommend/adventure/blind/course",
    "/recommend/adventure/blind/course/reveal",
    "/recommend/adventure/quest",
    "/recommend/adventure/seoul",
}


def test_launcher_identifies_integrated_backend():
    response = TestClient(app).get("/")

    assert response.status_code == 200
    assert response.json()["version"] == "mvp2-integrated-extensions"
    assert response.json()["entrypoint"] == "run:app"


def test_frontend_extension_contract_is_mounted():
    paths = set(app.openapi()["paths"])

    assert EXPECTED_EXTENSION_PATHS <= paths
