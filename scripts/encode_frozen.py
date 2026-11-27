"""Encode eligible product groups with a pretrained encoder, weights untouched (step 6).

Writes ``data/frozen_embeddings.npy`` and its manifest: one unit vector per
eligible group, from the name and ingredient text of the group's lowest barcode,
produced by a pinned revision of the encoder named in ``docs/PIPELINE.md``.
Nothing is trained and no label is read.

Encoding needs ``requirements-model.txt`` and downloads the model. ``--verify``
needs neither: it checks the stored file against its manifest and against the
texts of the current catalog. ``--reencode`` repeats the encoding and compares.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from basket.embeddings import (  # noqa: E402
    SCALE, StoredEmbeddings, encoder_text, ordered, quantize, texts_sha256,
)
from basket.pairs import representatives  # noqa: E402
from scripts.build_pairs import load_inputs  # noqa: E402
from scripts.fetch_data import write_atomic  # noqa: E402

OUTPUT = ROOT / 'data/frozen_embeddings.npy'
MANIFEST = ROOT / 'data/frozen_embeddings_manifest.json'
VERSION = 'frozen-embeddings-v1'
MODEL = 'sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2'
REVISION = 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42'
BATCH_SIZE = 32
# Largest difference, in int16 steps, accepted between two encodings of one text.
REENCODE_TOLERANCE = 64


def encode(products):
    """Return ``(int16 matrix, encoder facts)`` for the group representatives."""
    import sentence_transformers
    import torch
    import transformers

    texts = [encoder_text(row) for _, row in ordered(products)]
    model = sentence_transformers.SentenceTransformer(MODEL, revision=REVISION, device='cpu')
    model.eval()
    lengths = [len(ids) for ids in model.tokenizer(texts, truncation=False)['input_ids']]
    vectors = model.encode(texts, batch_size=BATCH_SIZE, normalize_embeddings=True,
                           convert_to_numpy=True, show_progress_bar=False)
    return quantize(vectors), {
        'max_seq_length': model.max_seq_length,
        'texts_truncated': sum(length > model.max_seq_length for length in lengths),
        'libraries': {'sentence-transformers': sentence_transformers.__version__,
                      'transformers': transformers.__version__, 'torch': torch.__version__},
    }


def build_manifest(matrix, facts, payload, products, catalog_hash):
    return {
        'version': VERSION,
        'file': OUTPUT.name,
        'file_sha256': hashlib.sha256(payload).hexdigest(),
        'model': MODEL,
        'model_revision': REVISION,
        'model_license': 'apache-2.0',
        'weights_updated': False,
        'device': 'cpu',
        'batch_size': BATCH_SIZE,
        **facts,
        'text': 'cleaned name, a period, then the ingredient text of the lowest eligible barcode',
        'rows': int(matrix.shape[0]),
        'row_order': 'eligible groups by lowest eligible barcode',
        'dimension': int(matrix.shape[1]),
        'dtype': 'int16',
        'scale': SCALE,
        'catalog_content_sha256': catalog_hash,
        'texts_sha256': texts_sha256(products),
        'note': ('Unit vectors rounded to int16 so cosines are computed with integer sums and '
                 'are identical across machines. Re-encoding on other hardware can differ by a '
                 'few int16 steps; the committed file is the reference for every ranking.'),
    }


def load_embeddings(products, catalog_hash) -> StoredEmbeddings:
    """Stored embeddings, checked against their manifest and the current catalog texts."""
    manifest = json.loads(MANIFEST.read_text())
    payload = OUTPUT.read_bytes()
    if hashlib.sha256(payload).hexdigest() != manifest['file_sha256']:
        raise SystemExit('Frozen embeddings differ from their manifest')
    if (manifest['model'], manifest['model_revision']) != (MODEL, REVISION):
        raise SystemExit('Frozen embeddings were produced by another model revision')
    if manifest['catalog_content_sha256'] != catalog_hash \
            or manifest['texts_sha256'] != texts_sha256(products):
        raise SystemExit('Frozen embeddings were encoded from different catalog texts')
    matrix = np.load(OUTPUT, allow_pickle=False)
    if matrix.shape != (manifest['rows'], manifest['dimension']):
        raise SystemExit('Frozen embeddings do not have the shape their manifest records')
    return StoredEmbeddings(products, matrix)


def npy_bytes(matrix) -> bytes:
    buffer = io.BytesIO()
    np.save(buffer, matrix, allow_pickle=False)
    return buffer.getvalue()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true',
                        help='Check the stored file without the encoder')
    parser.add_argument('--reencode', action='store_true',
                        help='Encode again and compare with the stored file')
    args = parser.parse_args()
    rows, digest, _ = load_inputs()
    products = representatives(rows)
    if args.verify or args.reencode:
        stored = load_embeddings(products, digest)
        message = f'{len(stored.row_of)} stored embeddings match their manifest and the catalog'
        if args.reencode:
            matrix, _ = encode(products)
            largest = int(np.abs(matrix.astype(np.int64) - stored.matrix).max())
            if largest > REENCODE_TOLERANCE:
                raise SystemExit(f'Re-encoding differs by {largest} int16 steps')
            message += f'; re-encoding differs by at most {largest} of {SCALE} int16 steps'
        print(message)
        return
    matrix, facts = encode(products)
    payload = npy_bytes(matrix)
    manifest = build_manifest(matrix, facts, payload, products, digest)
    write_atomic(OUTPUT, payload)
    write_atomic(MANIFEST, (json.dumps(manifest, ensure_ascii=False, indent=2) + '\n').encode())
    print(f'{manifest["rows"]} groups encoded in {manifest["dimension"]} dimensions; '
          f'{manifest["texts_truncated"]} texts exceed {manifest["max_seq_length"]} tokens')


if __name__ == '__main__':
    main()
