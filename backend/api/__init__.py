from backend.api.visualization import (
    AlignmentReadStore,
    InMemoryAlignmentReadStore,
    InMemoryStructureReadStore,
    InMemoryTrendReadStore,
    StructureReadStore,
    StructureSnapshot,
    TrendReadStore,
    TrendSnapshot,
    VisualizationReadApi,
)


def __getattr__(name: str) -> object:
    if name == "create_app":
        from backend.api.service import create_app

        return create_app
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "AlignmentReadStore",
    "InMemoryAlignmentReadStore",
    "InMemoryStructureReadStore",
    "InMemoryTrendReadStore",
    "StructureReadStore",
    "StructureSnapshot",
    "TrendReadStore",
    "TrendSnapshot",
    "VisualizationReadApi",
    "create_app",
]
