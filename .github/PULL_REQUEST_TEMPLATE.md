<!--
Thanks for contributing to BlackBar. Please fill in the sections below so reviewers can land the change quickly.
For details on the conventions used here, see CONTRIBUTING.md.
-->

## Summary

<!-- A short description of what this PR changes and *why*. Link related issues with `Fixes #123` or `Refs #123`. -->

## Type of change

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor (no behavior change)
- [ ] Documentation
- [ ] Test-only
- [ ] Chore / tooling / CI

## Checklist

- [ ] Tests added or updated for the behavior being changed
- [ ] Backend coverage gate passes locally (`cd backend && pytest`, fails under 80 %)
- [ ] Frontend coverage gate passes locally (`cd frontend && npm run test:coverage`, fails under thresholds in `vite.config.ts`)
- [ ] Docs in `docs/` or top-level `*.md` updated where behavior or setup changed
- [ ] No `tenant_*` regressions (BlackBar is single-tenant — multi-tenant code is forbidden, see audit Q1 and `docs/standards/`)
- [ ] DCO sign-off on every commit (`git commit -s`)
- [ ] `CHANGELOG.md` `[Unreleased]` section updated for any user-visible change

## Additional context

<!-- Screenshots, migration notes, deployment caveats, etc. -->
