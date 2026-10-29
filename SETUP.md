# Ignis on Windows: native, sandboxed, through a Cloudflare Tunnel

This guide has moved to [docs/](docs/). Start at the [README](README.md#documentation). The sections below point to
the pages that replace each former section of this file.

## Files

The installation folder and what each file is: [docs/installation.md, "The installation folder"](docs/installation.md#2-the-installation-folder).

## The sandbox

The AppContainer, its rights and its network: [docs/architecture.md, "The AppContainer"](docs/architecture.md#the-appcontainer).
The probes of `check`: [docs/installation.md, "Check the sandbox"](docs/installation.md#10-check-the-sandbox).

## Running it

The launcher's commands and processes: [docs/architecture.md, "Processes"](docs/architecture.md#processes).
What the launcher passes to Ignis and cloudflared: [docs/configuration.md](docs/configuration.md#what-the-launcher-passes-to-ignis).

## Plugins

Plugin exclusions, live plugin switches and Ignis's own layout: [docs/configuration.md, "Files in the vault"](docs/configuration.md#files-in-the-vault)
and [patches/README.md](patches/README.md).

## Augmented View: the desktop's model, used from Ignis

[docs/Plugin-Integration/Augmented-View.md](docs/Plugin-Integration/Augmented-View.md).

## The tunnel and the login

[docs/cloudflare.md](docs/cloudflare.md).

## The relay: desktop services used from Ignis, on the page's own address (patch 0006)

[docs/relay.md](docs/relay.md).

## The LaTeX build

[docs/Plugin-Integration/LaTeX.md](docs/Plugin-Integration/LaTeX.md).

## Installing and upgrading

[docs/installation.md](docs/installation.md), and for upgrades [docs/installation.md, "Upgrading"](docs/installation.md#13-upgrading).

## Memory on a phone

Why the browser is asked to keep the site's storage: patch 0004 in [patches/README.md](patches/README.md).

## When something is wrong

[docs/troubleshooting.md](docs/troubleshooting.md).
