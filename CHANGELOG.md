# Changelog

All notable changes to ComfyUI-Raffle are documented in this file.

## 2026-07-01

 **feat:** added `replace_underscores` boolean widget to replace underscores with spaces in output strings.

 **feat:** added wildcard negative tag matching (e.g. `*_halo`) to `negative_prompt`, `filter_out_tags`, and `exclude_taglists_containing` inputs.

 **performance:** optimized negative taglist exclusion pool filtering by separating literals (using fast set disjoint comparisons) from wildcard patterns.

**Changed files:**

- `raffle.py`
- `pyproject.toml`
- `CHANGELOG.md`
