# Open the UI without installing anything

**[`ltx-desktop-ui.html`](ltx-desktop-ui.html)** — download it and double-click.

That is the whole thing: one file, no install, no server, no Python, no
Electron, no GPU, no model weights. It is the app's real interface running
against a mock of its backend, so you can click through every screen.

On GitHub, use the **Download raw file** button — the web view will not run it.

## What you can do in it

It opens on a demo film, *The Relay*: two scenes, six shots, characters and
locations, a script, a completed render, a failed one to retry, and a
continuity warning to fix. Add scenes and shots, edit them, open the 3D Shot
Composer, queue renders and watch the queue run, and configure models in
**Settings → AI Models**.

Your changes are kept in that browser's storage, so they survive a reload.
Clear the page's site data (or open it in a private window) to start over.

## What it is not

It cannot generate video — nothing here runs a model, and no request leaves
your machine. Renders complete against stand-in media: labelled placeholder
frames, and a short clip the page draws for itself. Video export and a few
other pieces that need the desktop app say so rather than pretending.

## Keeping it current

This file is built from the same source as the app:

```bash
pnpm install
pnpm build:ui      # rewrites this file
```

`pnpm dev:ui` runs the same thing on a dev server with hot reload, which is
what you want while actually editing the interface.
Full detail: [`docs/UI_ONLY_MODE.md`](../docs/UI_ONLY_MODE.md).
