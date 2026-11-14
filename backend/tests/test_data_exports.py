from __future__ import annotations


def test_be_handoff_imports_discovery_and_retrieval_from_data_package() -> None:
    from changelens.data import discover, retrieve

    assert callable(discover)
    assert callable(retrieve)
