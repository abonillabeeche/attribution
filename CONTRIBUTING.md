# Contributing

Contributions to NVIDIA Attribution are welcome, including bug fixes,
documentation, rules, and connectors. Maintainers review proposed changes
for scope, correctness, tests, and compatibility with the project.

## Before you start

- Report reproducible upstream bugs through [GitHub Issues](https://github.com/dsx-ai-factory/attribution/issues/new?template=bug.yml).
  Follow the reproduction and evidence requirements in [SUPPORT.md](SUPPORT.md).
- Use [GitHub Discussions](https://github.com/dsx-ai-factory/attribution/discussions)
  for usage questions, feature requests, and design proposals. A maintainer opens
  a tracking issue when a proposal is accepted. Agree on the scope before starting
  implementation.
- Report security vulnerabilities through [SECURITY.md](SECURITY.md).
- Follow the [Code of Conduct](CODE_OF_CONDUCT.md).
- Keep the issue and pull request free of confidential, proprietary, personal,
  security-sensitive, and other non-public information.

## Submit a pull request

Create a branch for an accepted issue, make the change, and open a pull
request that links the issue. Include the test commands and results in the
pull request description. A maintainer reviews the pull request and must
approve it before it can merge.

## Signing Your Work

Sign each commit with the Developer Certificate of Origin (DCO):

```bash
git commit -s
```

The `-s` option adds the required `Signed-off-by` trailer. By signing off, you
certify the [Developer Certificate of Origin](https://developercertificate.org/).

### Full text of the DCO

```text
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.


Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

## Run the test gate

Install `uv`, Node.js 22, pnpm 10.11, and Docker, then run:

```bash
bash .ci/run-tests.sh all
```

The command runs the Docker end-to-end tests, the Library, Service, and Blueprint
Python suites, the generated-client and license checks, and the frontend tests
and build. Pass a suite name shown by `.ci/run-tests.sh` to run one part of the gate.

## Install the pre-commit hook

```bash
uv tool install pre-commit
pre-commit install
```

The license hook checks staged files for license compliance. When OpenAPI client
inputs change, the client hook regenerates the client and stops the commit if
the generated files need to be staged. Stage those files and retry the commit.
To regenerate the client manually, run
`service/service-app/openapi/generate-client.sh`.

## Title commits and pull requests

Pull requests are squash-merged, so the PR title becomes the commit subject on `main`. Write it as a [Conventional Commit](https://www.conventionalcommits.org/), `type(scope)!: summary`. CI checks the format and type; the rest is guidance.

- Types: `feat`, `fix`, `build`, `chore`, `ci`, `docs`, `perf`, `refactor`, `revert`, `style`, `test`.
- Scope is optional. Common scopes are `attribution-lib`, `service-app`, `blueprint`, `frontend`, `docs`, and `ci`.
- Write the summary in the imperative mood with no trailing period.
- Mark a removed or incompatible public API with `!` and add a `BREAKING CHANGE:` footer to the PR body that says what callers must change.
- The type signals the version bump for the next release of each touched component: `!` is major, `feat` is minor, `fix` is patch, and other types do not bump. A component still at `0.y.z` shifts each bump down one place: `!` is minor, and `feat` and `fix` are patch.

## Review interactive documentation

The attribution walkthrough is a Slidev application published through GitHub
Pages. Start with the [editing tutorial](docs/attribution-tour/TUTORIAL.md); the
[maintenance reference](docs/attribution-tour/MAINTAINING.md) and
[publishing guide](docs/github-pages.md) cover ongoing work and deployment.
