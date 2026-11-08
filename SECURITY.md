# Security

Photo runs a web server on your machine, so its security model matters even
though it is a local app.

## Design

- The server listens on `127.0.0.1` only. Network access must be enabled
  explicitly and then requires an access token.
- `Host` and `Origin` are validated on every request, which blocks DNS-rebinding
  attacks and other websites in your browser from talking to Photo.
- The engine (ComfyUI) listens on a random loopback port and is never exposed;
  its cloud "API nodes" are disabled.
- Engine source, Python packages and model files are pinned and verified by
  SHA-256 before use.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private vulnerability reporting
("Report a vulnerability" on the Security tab). You will get an answer within
7 days, and a fix or mitigation plan within 30 days for confirmed issues.
