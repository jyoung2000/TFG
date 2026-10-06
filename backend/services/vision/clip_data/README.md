# clip_data

Term lists vendored from **pharmapsychotic/clip-interrogator**
(https://github.com/pharmapsychotic/clip-interrogator, MIT License, commit
`bc07ce62c179d3aab3053a623d96a071101d11cb`), unmodified:

- `artists.txt`, `flavors.txt`, `mediums.txt`, `movements.txt`, `negative.txt`
  (the upstream `sites.txt` no longer exists at that commit).

The ranking code that uses them (`../clip_tagger.py`) is a port of the
upstream `LabelTable` / `rank_top` / `chain` design onto `transformers`'
CLIP — see `docs/INTEGRATED_UPSTREAMS.md`. The upstream LICENSE is reproduced
alongside as `LICENSE`.
