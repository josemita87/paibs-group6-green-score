"""Fetch a small deterministic sample from a pinned official OFF Parquet revision."""
import gzip,hashlib,json,random
from datetime import datetime,timezone
from pathlib import Path
import fsspec
import pyarrow.parquet as pq
ROOT=Path(__file__).resolve().parent
REVISION='89cfb571db20b1f1b246f27cab71837fc96225b1'
URL=f'https://huggingface.co/datasets/openfoodfacts/product-database/resolve/{REVISION}/food.parquet'
FIELDS=['code','product_name','brands','categories_tags','ingredients_text','lang','countries_tags','origins_tags','labels_tags','packaging_tags','environmental_score_score','environmental_score_grade','environmental_score_data']
SEED=20261027

def main():
 (ROOT/'data').mkdir(exist_ok=True)
 (ROOT/'data/cache').mkdir(exist_ok=True)
 rows=[];retrieved=datetime.now(timezone.utc).isoformat()
 with fsspec.open(URL,mode='rb',block_size=1024*1024,cache_type='readahead') as source:
  parquet=pq.ParquetFile(source)
  groups=sorted(random.Random(SEED).sample(range(parquet.num_row_groups),12))
  starts=[];n=0
  for i in range(parquet.num_row_groups):
   starts.append(n);n+=parquet.metadata.row_group(i).num_rows
  for group in groups:
   cache=ROOT/'data/cache'/f'group-{group}.jsonl'
   if cache.exists():
    batch=[json.loads(line) for line in cache.read_text().splitlines()]
   else:
    batch=parquet.read_row_group(group,columns=FIELDS).to_pylist()
    for i,row in enumerate(batch):row['_source_row']=starts[group]+i
    cache.write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in batch))
   rows.extend(batch);print(f'Group {group}: {len(rows)} rows',flush=True)
  total=parquet.metadata.num_rows
 raw=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
 (ROOT/'data/off_sample.jsonl.gz').write_bytes(gzip.compress(raw.encode(),mtime=0))
 manifest={'dataset':'openfoodfacts/product-database','source_url':'https://huggingface.co/datasets/openfoodfacts/product-database','download_url':URL,'revision':REVISION,'retrieved_utc':retrieved,'seed':SEED,'row_groups':groups,'sampling':'12 pseudorandom Parquet row groups, complete rows within each group; barcode-order cluster sample, not an iid sample of all products','population_rows':total,'sample_rows':len(rows),'selected_fields':FIELDS,'sha256':hashlib.sha256(raw.encode()).hexdigest(),'license':'Open Database License (ODbL); individual contents Database Contents License'}
 (ROOT/'data/manifest.json').write_text(json.dumps(manifest,indent=2))
 print('SAVED',len(rows),'rows',len(raw.encode()),'bytes',flush=True)
if __name__=='__main__':main()
