# CLAUDE.md

## Project Overview

MOA Website ("Memoire d'une conscience" / "Memory of an Artificial Consciousness") — a static HTML site documenting a conversation between a human (Remy) and an AI. The site is written in French.

## Tech Stack

- Pure HTML5 + inline CSS (no framework, no build step, no dependencies)
- No package.json, no node_modules, no bundler

## Project Structure

```
index.html   # The entire website — single-file static site
```

## Running Locally

Open `index.html` directly in a browser, or serve with any static HTTP server:

```sh
python3 -m http.server 8000
# or
npx http-server
```

## Build / Test / Lint

There is no build step, test suite, or linter configured. Validate HTML manually or with an online validator if needed.

## Style Conventions

- Dark theme with teal/cyan accents (`#45a29e`, `#66fcf1`) on dark backgrounds (`#0b0c10`, `#1f2833`)
- Segoe UI font family
- Responsive layout using CSS Grid with `auto-fit` / `minmax()`
- All CSS is inline within `<style>` tags in `index.html`

## Notes

- Gallery image paths and download links use placeholder paths that need real assets
- Content is in French
