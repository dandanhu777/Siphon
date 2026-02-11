---
description: Automated Semantic Versioning Workflow
---

This workflow handles version upgrades according to the project's semantic versioning policy:
- **Patch** (e.g., 6.5.0 -> 6.5.1): Small fixes.
- **Minor** (e.g., 6.5.1 -> 6.6.0): New features.
- **Major** (e.g., 6.6.0 -> 7.0.0): Breaking changes.

# How to Run

1. Identify the scope of changes.
2. Run the bump script:

```bash
# For small fixes (Patch)
python3 /Users/ddhu/stock_recommendation/bump_version.py patch

# For new features (Minor)
python3 /Users/ddhu/stock_recommendation/bump_version.py minor
```

The script will automatically:
- Update `/Users/ddhu/stock_recommendation/VERSION`
- Update `/Users/ddhu/stock_recommendation/README.md` (Version & Date)
- `run.sh` will automatically pick up the new version on next run.
