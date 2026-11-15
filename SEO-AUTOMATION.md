# SEO and social-preview automation

The writing hub has a reusable generator at `scripts/generate_seo.py`. It discovers `index.html` and published HTML pages in `research/` and `notes/`, derives article titles from `<h1>` and descriptions from `.subtitle` (or the first paragraph in `.publication-body`), then updates page metadata, structured data, a 1200×630 PNG social card, and `sitemap.xml`. It edits only the document head and sitemap, not article body text.

## One-time setup for a clone

Install the Git hook and its renderer dependency:

```sh
./scripts/install-git-hooks.sh
python3 -m pip install playwright
python3 -m playwright install chromium
```

After setup, committing a new or edited page under `research/` or `notes/` automatically regenerates its SEO tags, structured data, social-preview image, and sitemap entry before the commit is created. The generator also refreshes all other published pages so shared metadata stays consistent.

Run `python3 scripts/generate_seo.py` manually after updating pages outside a Git commit, and `python3 scripts/generate_seo.py --check` to validate the generated files. The current GitHub Pages branch-publishing model remains unchanged; this local commit hook is compatible with it. Edits made directly in GitHub's web editor do not run local Git hooks, so run the generator before publishing those edits.
