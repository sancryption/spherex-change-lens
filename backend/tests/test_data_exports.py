from __future__ import annotations


def test_be_handoff_imports_discovery_and_retrieval_from_data_package() -> None:
    from changelens.data import discover, retrieve

    assert callable(discover)
    assert callable(retrieve)


def test_data_package_exports_optional_catalogue_context_adapters() -> None:
    from changelens.data import (
        AllWISEAdapter,
        CatalogueAdapter,
        GaiaDR3Adapter,
        add_catalogue_context,
    )

    assert callable(add_catalogue_context)
    assert CatalogueAdapter.__name__ == "CatalogueAdapter"
    assert GaiaDR3Adapter.__name__ == "GaiaDR3Adapter"
    assert AllWISEAdapter.__name__ == "AllWISEAdapter"
