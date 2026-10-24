"""Text embedding adapter for the run library.

FastEmbed runs locally for now. A dedicated embedding server later is one new class
implementing ``Embedder`` plus a change to ``default_embedder()``; nothing else moves.
"""

from functools import cached_property
from pathlib import Path
from typing import Protocol

EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
# FastEmbed's default cache lives in the temp dir, which is wiped on reboot.
EMBEDDING_CACHE = Path.home() / ".cache" / "fastembed"


class Embedder(Protocol):
    """Turns texts into fixed-size vectors; ``dimension`` sizes the vector collection.

    ``model_name`` identifies the vectors, so a stored index is rebuilt when the model changes.
    """

    model_name: str
    dimension: int

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class FastEmbedEmbedder:
    """Local ONNX embeddings; the model loads (and downloads into ``cache_dir``) on first embed.

    Construction is free, so an empty run library never loads or downloads the model.
    """

    def __init__(self, model_name: str = EMBEDDING_MODEL, cache_dir: Path = EMBEDDING_CACHE) -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir

    @cached_property
    def model(self) -> object:
        # Imported here so chat and the offline tests never load FastEmbed or ONNX Runtime.
        from fastembed import TextEmbedding

        return TextEmbedding(model_name=self.model_name, cache_dir=str(self.cache_dir))

    @cached_property
    def dimension(self) -> int:
        return len(self.embed(["dimension probe"])[0])

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [vector.tolist() for vector in self.model.embed(texts)]


def default_embedder() -> Embedder:
    """The single swap point for the embedding backend."""
    return FastEmbedEmbedder()
