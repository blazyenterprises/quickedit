"""Build to a short staging path; verify before publishing a release installer.
Usage: python build_installer.py --unpacker path/to/innounp.exe
"""
from pathlib import Path
import argparse, hashlib, os, re, shutil, subprocess, tempfile

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unpacker', type=Path, required=True)
    parser.add_argument('--compiler', type=Path, default=Path(os.environ['LOCALAPPDATA']) / 'Programs/Inno Setup 6/ISCC.exe')
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    original = project / 'installer/QuickEdit.iss'
    script = original.read_text()
    source = re.search(r'^Source: "([^"]+)";', script, re.M)
    if not source:
        raise RuntimeError('No application Source entry found')
    app = (original.parent / source[1].removesuffix('\\*')).resolve()
    filename = re.search(r'^OutputBaseFilename=(.+)$', script, re.M)[1].strip() + '.exe'
    stage = Path(tempfile.mkdtemp(prefix='qe-build-'))
    print('Staging build at', stage, flush=True)
    # Retain staging files on failure for diagnosis; never publish partial output.
    shutil.copytree(app, stage / 'app')
    script = script.replace(source[1], str(stage / 'app' / '*'))
    script = script.replace('Compression=lzma2/ultra64', 'Compression=lzma2/normal')
    staged_script = stage / 'QuickEdit.iss'
    staged_script.write_text(script)
    subprocess.run([str(args.compiler.resolve()), '/O' + str(stage / 'build'), str(staged_script)], check=True)
    built = stage / 'build' / filename
    checked = stage / 'checked'
    subprocess.run([str(args.unpacker.resolve()), '-x', '-a', '-b', '-y', '-q', '-d' + str(checked), str(built)], check=True)
    count = 0
    for src in (stage / 'app').rglob('*'):
        if not src.is_file():
            continue
        dst = checked / '{app}' / src.relative_to(stage / 'app')
        if not dst.is_file() or hashlib.sha256(src.read_bytes()).digest() != hashlib.sha256(dst.read_bytes()).digest():
            raise RuntimeError('Installer verification failed: ' + str(src))
        count += 1
    release = project / 'release'
    release.mkdir(exist_ok=True)
    pending = release / (filename + '.verified-new')
    shutil.copyfile(built, pending)
    target = release / filename
    if target.exists():
        backup = release / (filename + '.' + hashlib.sha256(target.read_bytes()).hexdigest()[:12] + '.bak')
        if not backup.exists():
            shutil.copyfile(target, backup)
    os.replace(pending, target)
    print('Published', target, 'after verifying', count, 'files. Staging retained at', stage)

if __name__ == '__main__':
    main()
