# Interactive attribution walkthrough

This standalone [Slidev](https://sli.dev/) deck is an interactive companion to
the repository-level [How Attribution Works](../attribution.md) documentation.
It follows one compact example across the shared NVIDIA Attribution process,
verified against the bundled rules. The separate
[prose walkthrough](../attribution-walkthrough.md) remains a useful
non-interactive example.

The deck is a self-contained static application so a broader documentation
site can mount it without coupling its runtime or navigation. Set
`VITE_ATTRIBUTION_DOCS_BASE` at build time to point its phase links at a
rendered documentation route; by default, they point to the canonical Markdown
file on GitHub.

## Preview locally

From this directory:

```sh
corepack pnpm install
corepack pnpm dev
```

Use the on-screen controls or the arrow keys to page through the storyboard.
Each frame links directly to the corresponding section of
[`docs/attribution.md`](../attribution.md), and every frame has a shareable URL:

```text
http://localhost:3030/?scene=filter-standard
```

Other useful scene IDs include `initialize`, `ingest`, `extraction`,
`refine-scrub`, `outcome`, `post-outcome`, `collection`, and `result`. The old
`?scene=observations` URL remains an alias for `ingest`.

The Motion control defaults to half speed. Its `1×`, `½×`, and `¼×` settings
can also be shared in the URL as `motion=normal`, `motion=slow`, or
`motion=study`:

```text
http://localhost:3030/?scene=filter-late&motion=study
```

To verify the production bundle:

```sh
corepack pnpm build
```

## Publish and review on GitHub Pages

The `Attribution Process Walkthrough Pages` workflow builds the deck when files
in this directory change on `main`. It publishes the production deck to
`walkthroughs/attribution-process/` on the `gh-pages` branch and keeps the
branch's active PR previews intact. The Pages root remains a small, replaceable
landing page for a future comprehensive documentation site.

The `Attribution Process Walkthrough PR Preview` workflow publishes
same-repository pull requests beneath `pr-preview/pr-<number>/`, adds a
persistent preview link to the PR, updates the preview after each push, and
removes it when the PR closes. Fork pull requests do not receive previews
because GitHub gives them a read-only token. Each workflow builds with its
deployment-specific base path, and the deck uses hash routing so slide
navigation and reloads stay inside that path.

### First-time Pages setup

The first production or preview deployment creates the `gh-pages` branch. Once
that branch exists, a repository administrator must open **Settings → Pages**,
select **Deploy from a branch**, choose `gh-pages` and `/(root)`, and keep the
site's visibility private unless wider access has been approved. Rerun the
initial workflow afterward so its PR comment uses the private Pages address.
