# Security

This project intentionally exposes filesystem, shell, and network tools to an autonomous local agent. Treat it as experimental software with meaningful execution privileges.

## Security boundaries

### Workspace filesystem

File tools resolve paths before use and require the resolved path to remain inside the configured workspace. This also blocks symlink-based escapes.

### Shell execution

`run_shell` executes commands through `/bin/bash -lc` in the configured workspace. The supervisor applies an additional policy layer that blocks sensitive commands unless explicitly requested by the user.

The shell policy is not a sandbox. Run the agent under an OS account with only the permissions you are willing to give the model.

### Network access

`curl_internet` accepts HTTP/HTTPS only. Private and non-public address ranges are blocked by default, including redirect destinations. Private network access can be enabled deliberately with `AGENT_ALLOW_PRIVATE_NETWORK=1`.

DNS validation reduces common SSRF paths but should not be treated as a hardened network sandbox. For high-assurance use, enforce outbound policy at the OS/container/network layer as well.

### Secrets

Do not store credentials in the workspace. `.env` files are ignored by Git, but the agent can still access files inside its workspace if directed to them.

## Reporting vulnerabilities

Please open a GitHub issue without including credentials, private data, or exploit payloads that could harm other systems.
