# Security policy

## Supported release

Security fixes are developed against the newest published stable version. The
exact package version and available distribution files are shown on the
[PyPI project page](https://pypi.org/project/mudra-interact/). The public
core does not receive camera media, make network requests at runtime, or ship
model weights.

## Reporting a vulnerability

Please use [GitHub's private vulnerability reporting form](https://github.com/mayayaiinfra/Mudra-Interact-Core/security/advisories/new)
when it is enabled for this repository. If that form is unavailable, contact
the maintainers through the repository owner profile and ask for a private
reporting channel. Do not include credentials, personal data, real camera
frames or private ALLYK source in a public issue.

Include the affected release, Python/platform details, a minimal synthetic
reproducer and the expected versus observed behavior. Avoid posting a working
exploit before maintainers have had a reasonable opportunity to investigate.

## Release integrity

The package is published from a frozen source commit by GitHub Actions using
PyPI Trusted Publishing, a required-reviewer production environment and
per-file attestations. The release verifier checks exact source, artifact,
index, tag and downloaded-install identities. A passing local test run or
source push alone is not a publication or security certification.

The package makes no claim of independent penetration testing, complete
absence of vulnerabilities, recognition accuracy or cultural review.
