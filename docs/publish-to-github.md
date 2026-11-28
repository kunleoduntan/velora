# Publish to GitHub from the Desk

**Company Administration → Publish to GitHub** (platform administrators only). One click pushes an app, or the whole Velora project, to its GitHub repository. Each *profile* names the **company it belongs to**, so nothing is pushed to the wrong place.

## One-time setup
1. Install git on the server if it is missing: `sudo apt install git`.
2. On GitHub create a **personal access token** that can write to the repository (classic: `repo`; fine-grained: *Contents: Read and write*).
3. In the Desk: **New profile** → choose the company, what you are publishing, the repository address and branch, paste the token → **Save profile**. The token is stored encrypted and is never shown again.

## Two ways to publish
- **A project folder from your computer** (for Velora itself, or an app you edit locally): zip the folder (right-click → Compress), **Upload project zip**, then **Push to GitHub**. A single wrapper folder inside the zip is removed; `node_modules`, caches, `.env`, keys and passwords are left out automatically. Later uploads replace the files but keep the Git history.
- **An app already on the server** (created in the Desk): choose it in the profile. Velora refuses to push it unless it is installed in the company named on the profile.

## Safety
- The confirmation always shows the app, the company, the repository and the branch.
- A profile's project and company cannot be edited afterwards; make a new profile instead.
- No force-push. If the repository has commits this copy lacks, the push is refused and nothing is overwritten.
- The token never appears in the address, logs, audit trail or browser. Every push is audited (`publish.push`).

## Prefer to type it yourself?
**Show commands** prints the exact commands for your own computer:

    git init -b main
    git add -A
    git commit -m "Update"
    git remote add origin https://github.com/kunleoduntan/velora.git
    git push -u origin main

## Creating apps and DocTypes from the Desk
Switch **Developer mode** on (Company Administration). Then **Developer Studio** creates an app, and the **DocType Creator** creates DocTypes in it. Each new DocType gets a blank controller (`.py`) and client scripts (`.js`, `_list.js`); the result page links straight to them in the **File Explorer** to edit or paste code.
