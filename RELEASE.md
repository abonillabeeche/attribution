# Release policy

## Versioning

NVIDIA Attribution components have individual versions that follow [Semantic
Versioning 2.0.0](https://semver.org/). Component release tags include the
component name: `service-app-vMAJOR.MINOR.PATCH` for the Attribution Service,
`attribution-lib-vMAJOR.MINOR.PATCH` for the Attribution Library, and
`blueprint-vMAJOR.MINOR.PATCH` for the Blueprint.

Components release independently. A release of one component does not require
a new version or tag for another component.

The release-version source is the literal `__version__` in each component's
`__init__.py`:

| Component | Version source |
| --- | --- |
| Attribution Service | `service/service-app/app/__init__.py` |
| Attribution Library | `service/attribution-lib/src/attribution_lib/__init__.py` |
| Blueprint | `blueprint/src/attribution_blueprint/__init__.py` |

The Service, Library, and Blueprint each define this literal. Build-time
version stamping uses Git history to add local version metadata. It does not
change the committed release version.

The release process does not use `pyproject.toml` or `bundle-manifest.json` as
the release-version source. Removal of the manifest is follow-up work.

Compatibility commitments and supported interfaces are defined in
[SUPPORT.md](SUPPORT.md#support-lifecycle). Apply those commitments when choosing
the version for a change. The Library and Blueprint interfaces have the
limitations described in [Interface compatibility](SUPPORT.md#interface-compatibility).

Release notes identify known breaking changes and required migration steps.

## Release artifacts

For the initial process, a component tag on a reviewed default-branch commit is
the release. The process does not publish packages, prebuilt container images,
or Helm charts.

Prebuilt container images, including an NGC image, and a public Helm chart are
planned future artifacts. No publication date is committed for those artifacts.
Release notes must list the artifacts actually available for each release.

Maintainers publish releases after the required reviews and checks are complete.

## Merge and branch policy

Pull requests use squash merges into the default branch. Rebase feature branches
onto the default branch to keep them current. Do not merge the default branch
into a feature branch.

## Planned release process

CI tagging is not implemented yet. Maintainers must implement and validate it
before the first release under this process.

For each component release:

1. Change the component's version literal in its `__init__.py` in a pull
   request. Use that component's version and tag prefix.
2. Run the complete test gate with `bash .ci/run-tests.sh all`.
3. Prepare release notes that summarize user-visible changes, compatibility or
   migration requirements, known limitations, and any available artifacts.
4. Have the release changes reviewed and squash-merged to the default branch.
5. CI detects the changed version literal and creates the corresponding
   component tag on that merged commit. Components whose version literals did
   not change receive no new tag.

Project maintainers review version changes and control the CI release workflow.
Contributors propose version changes through pull requests. In the planned
process, CI creates release tags. Contributors and maintainers do not push
release tags by hand.
