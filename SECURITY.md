# Security and privacy

## Public-data policy

This is a public repository. Only publish the generated static brief and documentation intended for public reading.

Never commit:

- API keys, access tokens, cookies, passwords or credentials
- ChatGPT Library IDs, internal automation IDs or private connector metadata
- email addresses, account identifiers, home or workplace addresses, or other PII
- absolute local paths, temporary files, raw browsing logs or research caches
- proprietary source code or confidential company information

## Before every automated publish

The publishing pipeline must:

1. verify that the new date appears exactly once in the date input and article list;
2. verify that the latest date is selected and the archive count did not decrease;
3. validate the embedded JavaScript syntax;
4. scan the files being published for common credential, internal-ID, email and local-path patterns;
5. stop before commit if any validation fails.

## Reporting

Please open a GitHub issue for public-content problems that do not contain sensitive information. Do not paste secrets or personal data into an issue.

