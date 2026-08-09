# GUI / Assistant Bridge Architecture

GUI editors -> input/*.json -> schema + cross-file validator -> renderer -> output/*.mp4 -> verification -> render_manifest -> assistant_bundle.zip

The portable bundle is the unit of collaboration and version control.

Recommended production backend:
- GitHub: JSON/code/versioning/diffs/rollback and assistant edits.
- Shared media storage: rendered videos and other large artifacts.

The GUI should never store critical state only inside browser/session memory.
