"""Regression: the fallback runner's monkeypatch shim must support both call forms
(and behave like pytest's), so both runners exercise identical semantics."""
import types
import config


def test_setattr_string_form(monkeypatch):
    original = config.allowed_file
    monkeypatch.setattr("config.allowed_file", lambda name: "sentinel")
    assert config.allowed_file("x.pdf") == "sentinel"
    # restoration is checked by the next test (pytest and the shim both undo at teardown)
    assert original is not config.allowed_file


def test_string_form_was_restored():
    assert config.allowed_file("a.pdf") is True


def test_setattr_object_form(monkeypatch):
    obj = types.SimpleNamespace(value=1)
    monkeypatch.setattr(obj, "value", 2)
    assert obj.value == 2
