# Director Studio · 片场

A local-first, open-source video workbench for product stories and creator-led content.
Plan with a director, refine one shot or transcript segment, compare candidates, and choose
reuse, local composition or generation with visible costs and review gates.

[中文](README.md) · [Installation](docs/installation.md) · [Detailed guide](docs/user-guide.md) · [MIT](LICENSE)

## Who it is for

Creators making product/brand shorts, talking-head or interview content, and knowledge videos;
internal content producers who need controlled revisions and project cost records;
developers extending a readable React/FastAPI workflow. This is an alpha for technically
comfortable users, not a hosted service or a professional timeline-editor replacement.

## Features

- Context, director and artifacts in a resizable three-pane workbench.
- Editable scripts, storyboards, keyframes, image and video candidates.
- Scoped revision proposals, candidate adoption and content-version recovery.
- Source intervals separate from composition time; original audio follows the same cuts.
- Local sentence/segment ASR on Apple Silicon, with timestamped SRT import as a recovery path.
- Caption correction does not cut audio; keep/remove/reorder/boundary edits are applied explicitly.
- Rule-based provider compatibility, quotes, alternatives and exclusion reasons; no invented success rates.
- Project budget reservations, idempotency, durable jobs, uncertain-submission handling and download recovery.
- Two versioned, allowlisted internal skills: brand-shot design and creator rough-cut proposals.
- Reviewed MP4, SRT and portable project ZIP exports, including assets and recent versions.

## Quick start

Verified target: Apple Silicon Mac. Install Git, uv, Node.js 22+ and FFmpeg first.

```bash
git clone https://github.com/Gavinluo19/director-studio.git
cd director-studio
bash scripts/start.sh
```

Open http://127.0.0.1:8768/ and keep the terminal open. Press Control+C to stop the API and worker.
The script does not install a login agent. Logs are stored in the local data directory under `logs/`.
On unsupported platforms the core may install, but that does not establish end-to-end product support.

## Try it without a paid provider

Import your own clip plus a timestamped SRT in a creator project, select segments, apply the edit,
approve the reuse route, preserve original audio, render locally, review and export.
Alternatively run the synthetic media smoke test described in the Chinese README.

For local automatic transcription, prepare the optional model separately:

```bash
app/backend/.venv/bin/python scripts/download_asr.py --yes
```

The model download uses network and disk; media is not uploaded. Without weights, use SRT import.
Local ASR is segment-level, not arbitrary word-accurate editing.

## Models, privacy and costs

Configure your own accounts, exact model IDs, supported settings and prices in Models & Connections.
Presets are editable starting points, not evidence that your account or every adapter has been validated.
Cloud generation sends the task inputs to the provider you configure. Local project storage does not
make all AI inference offline. Review [SECURITY.md](SECURITY.md) before processing sensitive material.
The cost ledger is an application reservation/estimate/reconciliation tool, not the provider's bill.
Open-source software does not make cloud models free or guarantee commercial output quality.

## Status and contribution

Release: `v1.2.0-alpha.1`. No multi-user collaboration, native installer, complete infinite canvas,
external plugin marketplace or production SLA. Provider execution and media quality require separate
account/sample validation. See [verification](docs/verification.md), [limitations](docs/known-limitations.md),
[contributing](CONTRIBUTING.md) and [architecture](docs/architecture.md).

MIT covers this repository's original source. Model weights, providers, dependencies, fonts and media
retain their own licenses and terms: [third-party notices](THIRD_PARTY_NOTICES.md).
