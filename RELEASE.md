# Release

1. Install: `pip install bump2version`
2. Update `CHANGELOG.md` — add a `## [x.y.z] - YYYY-MM-DD` section with your changes
3. Bump version and tag: `bump2version minor` (or `patch` / `major`)
4. Push the release commit and tag: `git push --follow-tags`

GitHub Actions will then:
- Run tests
- Build the wheel and source tarball
- Create a GitHub Release using the `CHANGELOG.md` section for this version
- Publish to PyPI
