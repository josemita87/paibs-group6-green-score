"""Read stored product embeddings and compare them exactly (pipeline step 6).

A pretrained encoder turns one text per product group into a unit vector. The
vectors are stored as 16-bit integers so that a cosine can be computed with
integer arithmetic: the result is then identical on every machine, which lets CI
verify rankings against a rebuild without installing the encoder.

This module needs NumPy only. Encoding lives in ``scripts/encode_frozen.py``.
"""
import hashlib
import math

import numpy as np

SCALE = 32767   # a unit vector component of 1.0 maps to the largest int16


def encoder_text(row) -> str:
    """The text one product contributes: its cleaned name, then its ingredient text."""
    return f"{row['name'] or ''}. {row['ingredients_text'] or ''}".strip()


def ordered(products: dict[int, dict]) -> list[tuple[int, dict]]:
    """Group representatives in the row order of the stored matrix: by barcode."""
    return sorted(products.items(), key=lambda item: item[1]['code'])


def texts_sha256(products: dict[int, dict]) -> str:
    """Fingerprint of the barcodes and texts, in matrix row order."""
    digest = hashlib.sha256()
    for _, row in ordered(products):
        digest.update(f"{row['code']}\t{encoder_text(row)}\n".encode())
    return digest.hexdigest()


def quantize(vectors) -> np.ndarray:
    """L2-normalize float vectors and round them to int16."""
    vectors = np.asarray(vectors, dtype=np.float64)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.all(norms > 0):
        raise ValueError('An embedding has zero length')
    return np.rint(vectors / norms * SCALE).astype(np.int16)


class StoredEmbeddings:
    """Quantized vectors of the group representatives, addressed by group id."""

    def __init__(self, products: dict[int, dict], matrix: np.ndarray):
        if matrix.dtype != np.int16 or matrix.ndim != 2:
            raise ValueError('Embeddings must be a two-dimensional int16 matrix')
        if matrix.shape[0] != len(products):
            raise ValueError(f'{matrix.shape[0]} embeddings for {len(products)} product groups')
        self.row_of = {group_id: index for index, (group_id, _) in enumerate(ordered(products))}
        self.matrix = matrix.astype(np.int64)
        self.squares = [int(value) for value in (self.matrix * self.matrix).sum(axis=1)]

    def cosine(self, first: int, second: int) -> float:
        """Cosine of two groups from exact integer sums; only the last division is a float."""
        row, other = self.row_of[first], self.row_of[second]
        dot = int(self.matrix[row] @ self.matrix[other])
        return dot / math.sqrt(self.squares[row] * self.squares[other])
