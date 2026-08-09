# AnimationVideoTool — Local GUI MVP V0.1

A local web GUI for the AI Electronics Animation Engine benchmark pipeline.

## Recommended: one-command Docker hosting

This is the easiest and most reproducible path because FFmpeg and eSpeak NG are installed inside the container.

### Windows

1. Install Docker Desktop.
2. Clone/download this repository.
3. Double-click `run_docker_windows.bat`.
4. Open `http://127.0.0.1:7860` if your browser does not open automatically.

Stop it with `stop_docker_windows.bat`.

### macOS / Linux

```bash
chmod +x run_docker_mac_linux.sh stop_docker_mac_linux.sh
./run_docker_mac_linux.sh
```

Open `http://127.0.0.1:7860`.

Stop it with:

```bash
./stop_docker_mac_linux.sh
```

Project workspaces persist in the local `projects/` directory through a Docker bind mount.

## Native Python mode

Prerequisites:
- Python 3.10+
- FFmpeg and ffprobe on PATH
- eSpeak NG or eSpeak on PATH

Check native dependencies:

```bash
python scripts/doctor.py
```

### Windows

Double-click `run_windows.bat`.

### macOS/Linux

```bash
./run_mac_linux.sh
```

The GUI launches on `http://127.0.0.1:7860`.

## What the GUI does

- Loads all 9 Schema V0.1 JSON contracts into editable tabs.
- Validates JSON Schema and cross-file constraints.
- Runs the deterministic capacitor benchmark renderer.
- Previews the generated MP4.
- Produces a verification report and render manifest.
- Exports/imports a portable assistant bundle.
- Keeps project state as ordinary files under `projects/`.

## Current limitation

Renderer V0.1 is still benchmark-specific. It proves the local GUI, contract validation, render execution, project persistence, and assistant round-trip. The next renderer milestone is the generic scene-action registry so new topics can be rendered without scene-specific Python code.

## Shared development workflow

GitHub is the source of truth for GUI/code/schema changes. Rendered videos and user project workspaces stay local by default and are ignored by Git.
