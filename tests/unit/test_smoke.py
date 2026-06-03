"""Import smoke test for the scaffold (task 001-T1).

Verifies the src-layout package resolves and imports cleanly after `uv sync`,
before any business logic exists. No EARS requirement is uniquely T1's — this is
the enabling check that every later task builds on.
"""


def test_ncs_imports_cleanly() -> None:
    import ncs

    assert ncs is not None


def test_ncs_exposes_version() -> None:
    import ncs

    assert isinstance(ncs.__version__, str)
    assert ncs.__version__
