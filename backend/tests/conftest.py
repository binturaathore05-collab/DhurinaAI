"""Shared test setup.

B1 (class + parent consent) is enforced for every AI action. Most tests are about other features and log in a
student who has not filled in a class yet, so the B1 gate is switched off for them here. Tests that check B1 itself
carry @pytest.mark.consent_gate and get the real gate.
"""
import os

import pytest

os.environ.setdefault("DATA_JOBS", "0")   # no background backups / clean-ups while testing


def pytest_configure(config):
    config.addinivalue_line("markers", "consent_gate: run with the real B1 class / parent-consent gate")


@pytest.fixture(autouse=True)
def _b1_gate_off_unless_tested(request, monkeypatch):
    if request.node.get_closest_marker("consent_gate"):
        return
    from app.services import consent
    monkeypatch.setattr(consent, "gate_message", lambda st: None)
