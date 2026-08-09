#!/usr/bin/env python3
import shutil, sys
from importlib import metadata

print('AnimationVideoTool local dependency check')
print('Python:', sys.version.split()[0])
checks=[]
for cmd in ('ffmpeg','ffprobe'):
    path=shutil.which(cmd)
    checks.append((cmd, bool(path), path or 'NOT FOUND'))
tts=shutil.which('espeak-ng') or shutil.which('espeak')
checks.append(('TTS (espeak-ng/espeak)', bool(tts), tts or 'NOT FOUND'))
for name, ok, detail in checks:
    print(('PASS' if ok else 'FAIL'), name, '-', detail)

for pkg in ('gradio','jsonschema','opencv-python-headless','opencv-python','numpy'):
    try:
        print('PKG ', pkg, metadata.version(pkg))
    except metadata.PackageNotFoundError:
        pass

if not all(x[1] for x in checks):
    print('\nMissing native dependency. Docker mode avoids manual FFmpeg/TTS setup.')
    sys.exit(1)
print('\nAll native runtime dependencies found.')
