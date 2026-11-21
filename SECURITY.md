# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub Security Advisories: open the repository's **Security** tab and choose **Report a vulnerability**. Do not open a public issue for a security problem. Include the Xlens version, steps to reproduce, and a minimal generated workbook if one is needed. Do not attach real confidential models.

## Threat model

Xlens opens workbooks that may come from someone else, and passes their contents to an AI assistant and a local browser page. A workbook is therefore untrusted input.

- **Workbook text in the map.** Labels, sheet names, cell text and formulas are HTML-escaped when rendered. Data embedded in the page as JSON is escaped so it cannot close the script element.
- **Prompt injection.** Workbook text can contain instructions aimed at the assistant. The skill tells the assistant to treat workbook content as data, quote it, and never follow instructions found in it. This reduces the risk but cannot remove it for a model.
- **Local viewer.** The map server binds to `127.0.0.1` only and requires a random per-session token. It checks the `Host` header to block DNS-rebinding, and sends a Content-Security-Policy.
- **No network use by Xlens.** Xlens does not send workbooks anywhere. Tool results do reach the AI provider behind your chat app, as described in the README.

Out of scope: a malicious local user on the same machine, and the security of the AI host itself.
