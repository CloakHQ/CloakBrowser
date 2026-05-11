# Security Policy

## Supported Versions

Security fixes are provided for the latest released version of this project.

| Version | Supported |
| ------- | --------- |
| Latest release | :white_check_mark: |
| Older releases | Best effort |
| Unmaintained / archived releases | :x: |

If you are unsure whether a version is supported, please include the exact package version, commit hash, and installation method in your report.

## Reporting a Vulnerability

Please do **not** report security vulnerabilities through public GitHub issues.

To report a vulnerability, use one of the following private channels:

1. GitHub Private Vulnerability Reporting, if enabled for this repository.
2. A private GitHub Security Advisory.
3. The maintainer security contact listed in the repository, if available.

When reporting a vulnerability, please include:

- Affected package name and version
- Affected component or file path
- Vulnerability type
- Impact
- Safe reproduction steps
- Expected behavior
- Actual behavior
- Relevant logs, screenshots, or request/response samples
- Suggested remediation, if available

## Disclosure Process

We follow coordinated vulnerability disclosure.

After receiving a report, we aim to:

1. Acknowledge receipt.
2. Confirm whether the issue is in scope.
3. Reproduce and assess the vulnerability.
4. Prepare and test a fix.
5. Release a patched version.
6. Publish a security advisory when appropriate.
7. Request a CVE when the vulnerability meets CVE assignment criteria.

Please allow a reasonable coordination period before public disclosure.

## Scope

Security reports are welcome for vulnerabilities that affect this project’s code, package, binaries, or documented deployment modes.

Examples of in-scope issues include:

- Authentication or authorization bypass
- Path traversal
- Arbitrary file read, write, or deletion
- Remote code execution
- Sensitive information disclosure
- Insecure default network exposure
- Unsafe handling of browser debugging interfaces
- Denial of service caused by unbounded resource creation
- Dependency vulnerabilities that are directly exploitable through this project

Out-of-scope reports include:

- Social engineering
- Physical attacks
- Issues requiring access to a compromised maintainer account
- Spam, phishing, or abuse reports unrelated to this project’s code
- Vulnerabilities only affecting unsupported or modified forks
- Reports without enough information to reproduce or assess impact

## Safe Harbor

Security research conducted in good faith and within the scope of this policy is welcome.

Please avoid:

- Accessing, modifying, or deleting data that does not belong to you
- Disrupting service availability
- Exfiltrating secrets or user data
- Running destructive tests against third-party systems
- Publicly disclosing details before a fix or mitigation is available

If you accidentally access sensitive data during testing, stop immediately and include only the minimum necessary evidence in your private report.

## Credit

We are happy to credit researchers in the published advisory unless they request otherwise.
