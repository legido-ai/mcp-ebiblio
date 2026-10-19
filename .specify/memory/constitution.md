<!--
Template: SDD Starter Constitution v1.0.0
This is the initial template version. No prior versions exist.
Projects adopting this template should replace placeholder tokens
(in square brackets) with project-specific values.
-->

# [PROJECT_NAME] Constitution

This document governs all development on this project. It is the supreme
authority for process, quality, security, and governance decisions.
Specifications are the source of truth. No implementation proceeds without an
approved specification. No merge or acceptance occurs without completing all
compliance and checklist requirements.

## Core Principles

### I. SDD Cycle Discipline

- All work MUST begin with a written specification approved through the
  project's spec workflow before any implementation begins.
- No code may be committed for a feature or fix that lacks an approved
  specification referencing it.
- Every merge or acceptance gate requires completion of the Compliance Gate
  checklist below.
- Specifications are the authoritative source of truth for requirements,
  acceptance criteria, and scope boundaries.

### II. Test-First (NON-NEGOTIABLE)

- TDD is mandatory. Every feature and every bug fix MUST include at least one
  new automated test written before or alongside the implementation.
- `make test` is the canonical test command. It MUST run the full test suite
  and MUST pass with zero failures before any merge or acceptance.
- A `/tests` directory MUST exist for automated regression and compliance
  tests. Supporting harness scripts may live at the repository root when a
  stable path is required by the toolchain.
- Any failing test is a hard blocker. No exceptions without documented
  justification in the plan's compliance or complexity tracking section.

### III. Security-First Secrets Management

- All secrets (API keys, tokens, passwords, private keys) MUST be supplied
  through environment variables only. No secrets in code, committed
  configuration files, or container images.
- A `.env.example` file listing every required environment variable with
  placeholder values and documentation MUST be committed to the repository.
- The actual `.env` file MUST never be committed and MUST be listed in
  `.gitignore`.
- The runtime or entrypoint MUST validate that all required environment
  variables are set before starting.
- An automated secret audit (scanning for committed secrets or hard-coded
  credentials) MUST be included in the test suite or CI-equivalent checks.

### IV. Workflow Requirements

- A `Makefile` MUST exist at the project root with at least `run` and `test`
  targets.
- A `README.md` MUST document at minimum: prerequisites, quickstart, and
  architecture overview.

### [PRINCIPLE_5_NAME]

[PRINCIPLE_5_DESCRIPTION]

## Compliance Gate

Before an implementation plan may proceed, verify:

- [ ] Every planned feature or fix includes at least one test in `/tests`
- [ ] `make test` runs the full test suite with no failures
- [ ] No security or secret-management rules are violated
- [ ] Makefile and README minimum requirements are satisfied
- [ ] All constitutional rules are respected

Any exception MUST be documented in the plan's complexity tracking section
with justification.

## Governance

- **Supremacy**: This constitution supersedes any conflicting local
  conventions, tool configurations, or ad-hoc practices.
- **Amendment procedure**: Changes to this constitution MUST follow the
  project's amendment workflow: propose the change, obtain approval, update
  this document, record the change in `CHANGELOG.md`, and update the version
  and last-amended date.
- **Versioning policy**: Constitution versions follow semantic versioning.
  MAJOR for incompatible removals or redefinitions of principles, MINOR for
  added principles or materially expanded guidance, PATCH for wording
  clarifications or non-semantic refinements.
- **Compliance reviews**: Before planning or merging, maintainers MUST verify
  compliance with this constitution and record verification in the plan's
  Constitution Check section.

**Version**: [CONSTITUTION_VERSION] | **Ratified**: [RATIFICATION_DATE] |
**Last Amended**: [LAST_AMENDED_DATE]
