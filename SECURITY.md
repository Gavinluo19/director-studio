# Security and privacy

This alpha is a single-operator localhost application. It is not a multi-tenant server.
Keep it bound to `127.0.0.1`; do not expose the port through a public tunnel or reverse proxy.

API writes use a local session, CSRF token and project revision. API credentials are stored
server-side using macOS Keychain where available, with an explicitly recorded encrypted-file fallback.
The fallback master key lives alongside the data and is not a replacement for disk encryption.

Local ASR and FFmpeg processing keep raw media local. Opting into cloud generation sends the
configured service the prompts, selected references or other task inputs it needs. AI review and
director work can send extracted frames and text. Inspect provider terms before using confidential media.

Project ZIP exports contain actual media and project content. They omit API credentials; they are
still sensitive content, not sanitized public demos. Logs, databases, `.vault-key`, transcripts and
signed download URLs must not be included in public issues or commits.

Report security problems through the repository's private vulnerability reporting feature when
available. If it is unavailable, do not post sensitive reproduction material in a public issue;
contact the maintainer through a channel they have explicitly provided.
