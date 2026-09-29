# ComfyUI with ComfyUI-Manager (core 0.3.76, Manager V3.37)

## Overview

The deployed application is a single web service that hosts the ComfyUI node-graph
editor for image-generation workflows, extended with the ComfyUI-Manager custom
node, which adds tooling for managing custom node packs, models, snapshots and the
ComfyUI installation itself. It runs a CPU-only backend with a single default user
profile and no login; the core editor API and the manager API are served from the
same HTTP endpoint, with the manager installed as a custom node inside the same
application.

## Services

### workflow-submission
- contract: Submits a node-graph prompt for execution and manages the execution queue; owns the queue state, the interrupt operation and the free-memory flags that the editor drives.
- exposure: public

### workflow-history
- contract: Keeps the record of executed prompts and their outputs; supports retrieval by prompt identifier, clearing the whole history and deleting individual history entries.
- exposure: public

### node-registry
- contract: Publishes the definitions of every available node class (inputs, outputs, display names, categories, description) that the graph editor uses to render and validate workflows.
- exposure: public

### model-inventory
- contract: Lists the model files and embeddings available in the model folders, exposing the full recursive model inventory with file metadata, plus a safetensors-metadata reader for a chosen model file.
- exposure: public

### image-upload
- contract: Receives image and mask uploads and stores them into the working directories, deduplicating by content hash and supporting overwrite and subfolder placement; mask uploads are merged back into their referenced original image.
- exposure: public

### image-viewing
- contract: Serves stored image assets back to the browser, resolving the requested file from a selected asset directory and subfolder, and offering preview re-encoding and channel selection (rgba, rgb, alpha).
- exposure: public

### system-status
- contract: Reports machine and process telemetry (memory, compute device, ComfyUI, frontend and template versions, python and pytorch versions, command-line arguments) and the server feature flags.
- exposure: public

### user-profile
- contract: Manages the user profiles and the per-user application settings that are stored on the server rather than in the browser.
- exposure: public

### user-data-file
- contract: Lists, reads, writes, moves and deletes the files inside a user's data directory, with directory listing, recursion and file-metadata options.
- exposure: public

### custom-node-content
- contract: Serves the assets and metadata contributed by installed custom nodes: the frontend extension scripts, the example workflow templates, the i18n translations and the global subgraphs.
- exposure: public

### server-diagnostics
- contract: Exposes the internal diagnostics surface used by the frontend: application log retrieval and subscription, the folder-path map and directory file listings.
- exposure: public

### custom-node-catalog
- contract: Queries the registry of custom node packs across the configured channels: node-to-pack mappings, the full node pack list, alternatives, installed packs, available versions and per-pack import failure information.
- exposure: public

### custom-node-lifecycle
- contract: Installs, reinstalls, fixes, updates, uninstalls and disables custom node packs, including installation from a git repository URL or from pip, all funneled through a shared background work queue that reports progress.
- exposure: public

### model-download
- contract: Lists the downloadable external model catalog and triggers model file downloads into the model directories, honoring the model catalog membership checks before a download is queued.
- exposure: public

### comfyui-update
- contract: Reports the available ComfyUI versions and the currently installed one, switches the ComfyUI version, queues an update of the ComfyUI installation, and restarts the application.
- exposure: public

### snapshot-management
- contract: Captures, lists, restores and removes snapshots of the installed custom node and pip package state.
- exposure: public

### manager-preferences
- contract: Reads and updates the ComfyUI-Manager preferences: preview method, database mode, component policy, update policy, share option, the active content channel and the manager version.
- exposure: public

### component-library
- contract: Saves and loads reusable workflow components (named workflow fragments, optionally packaged) in the manager's component store.
- exposure: public

### community-sharing
- contract: Publishes generated artworks, their workflows and model information to third-party sharing platforms (comfyworkflows and Matrix), and stores and retrieves the credentials and settings for those platforms and for openart, youml and esheep.
- exposure: public

### manager-announcement
- contract: Fetches and renders the manager's news page from a remote wiki and appends the current ComfyUI and manager version lines.
- exposure: public

## Systems

### workflow engine - execution
- description: Validates graph prompts, executes the node graph on the CPU backend, and maintains the running and pending task queues.

### client channel - websocket sessions
- description: A websocket session per connected editor; carries status, executing-node, progress and image-preview events to the browser and negotiates feature flags.

### filesystem - asset directories
- description: The input, output, temp and models directories resolved through the folder-path registry, including the file-reference convention that ties a file name to its directory.

### filesystem - user profile store
- description: The user data directory holding the per-user settings file and user data files, scoped to the single default profile in this deployment.

### configuration - manager settings store
- description: The persisted ComfyUI-Manager settings file that records channel selection, policies, preview method and network mode.

### configuration - channel registry
- description: The channel list that names the remote sources (channels) used to fetch the custom node and model catalogs.

### integration - remote catalog fetcher
- description: Fetches and caches the JSON catalogs (custom node list, node mappings, model list, alternatives, github stats) from remote channel URLs.

### orchestration - background work queue
- description: A single worker thread that serializes the manager's install, update, uninstall, fix, disable and model-download jobs and publishes progress over the client channel.

### integration - git
- description: Clones, pulls, resets and switches git repositories for custom node packs and for the ComfyUI installation itself.

### integration - model downloader
- description: Downloads model files from remote URLs using the requests/urllib/torchvision machinery and huggingface hub for repository downloads.

### storage - snapshot store
- description: The directory holding JSON snapshots of the custom node and pip package state for restore.

### storage - component store
- description: The directory holding saved workflow components (json and pack files) for reuse.

### integration - sharing providers
- description: Outbound publishing to the comfyworkflows sharing platform and to Matrix rooms, plus the stored credentials for the openart, matrix, comfyworkflows, youml and esheep providers.

## Roles

- default user: the single browser profile; every request is attributed to it and its data and settings live under that profile.
- system user (reserved): profiles carrying the reserved system prefix are internal and rejected on the public user API.

## Service-system mapping

- workflow-submission relies on the workflow engine for queue management and on the client channel for status events.
- workflow-history relies on the workflow engine for the execution history.
- node-registry relies on the workflow engine for the loaded node class definitions.
- model-inventory relies on the asset directories for the model folder scan and on the workflow engine for safetensors header parsing.
- image-upload relies on the asset directories for upload placement and duplicate detection.
- image-viewing relies on the asset directories to resolve and serve stored assets.
- system-status relies on the workflow engine for device and memory reporting.
- user-profile relies on the user profile store for profiles and settings persistence.
- user-data-file relies on the user profile store for the user data directory.
- custom-node-content relies on the asset directories and on the frontend static file serving for custom node assets.
- server-diagnostics relies on the application log buffer and the asset directories for file listings.
- custom-node-catalog relies on the remote catalog fetcher, the channel registry and the git integration for pack state.
- custom-node-lifecycle relies on the background work queue, the git integration and the remote catalog fetcher.
- model-download relies on the remote catalog fetcher for the model catalog and on the model downloader for fetching.
- comfyui-update relies on the git integration to switch and update ComfyUI and on the process restart mechanism.
- snapshot-management relies on the snapshot store and the remote catalog fetcher.
- manager-preferences relies on the manager settings store and the channel registry.
- component-library relies on the component store.
- community-sharing relies on the sharing providers and the asset directories for the artwork files.
- manager-announcement relies on the remote catalog fetcher to retrieve the news page.