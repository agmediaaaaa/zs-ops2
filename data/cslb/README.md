# CSLB data directory

Raw downloads and normalized CSVs are **gitignored** (large files).

```bash
python scripts/ingest_cslb_master_list.py --download
python scripts/ingest_cslb_master_list.py --from-raw data/cslb/raw \
  --status CLEAR --expires-within 120 --slice-name expires120_clear
```

See [docs/cslb-contractor-ingest.md](../../docs/cslb-contractor-ingest.md).
