"""Client-side photo inspection without server round trips for zoom and pan."""

from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import uuid4

from nicegui.element import Element


@dataclass
class PhotoViewerState:
    """Keep an observation's photo selection across quiz redraws."""

    index: int = 0
    view: str = "photo"
    cache_key: str = field(default_factory=lambda: uuid4().hex)
    generation: int = 0

    def reset(self) -> None:
        """Start a new observation without retaining its predecessor's framing."""
        self.index = 0
        self.view = "photo"
        self.generation += 1


class PhotoCanvas(Element, component="photo_canvas.js"):
    """Show a zoomable photo with loading recovery and accessible controls."""

    def __init__(
        self, source: str, state: PhotoViewerState, *,
        label: str = "Observation photo", on_next: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._props.update(source=source, cache_key=state.cache_key,
                           generation=state.generation, label=label, has_next=on_next is not None)
        self.classes("w-full h-full min-h-0 flex-1")
        if on_next is not None:
            self.on("next", lambda _: on_next())
