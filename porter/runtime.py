"""Download and verify the Wine runtimes (cached once per machine) and build native tools."""
import hashlib
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from . import paths

RUNTIMES = {
    'wine-staging': {
        'url': 'https://github.com/Gcenx/macOS_Wine_builds/releases/download/11.18/wine-staging-11.18-osx64.tar.xz',
        'sha256': 'b63704b91af269bc026a87f12bd297c4a50caaf570c322e600b6621ef918f127',
        'check': paths.DECODER_WINE / 'bin/wine',
    },
    'gptk': {
        'url': 'https://github.com/Gcenx/game-porting-toolkit/releases/download/Game-Porting-Toolkit-3.0-3/'
               'game-porting-toolkit-3.0-3.tar.xz',
        'sha256': 'd377683937340f914823dbb2e1252b329cbf834ff58907d0293db8cebf0e392e',
        'check': paths.GAME_WINE / 'bin/wine64',
    },
}
NATIVE_TOOLS = ['fa-filter', 'srep', 'clshost.exe', 'fg-arc-map']


def log(msg):
    print(f'[porter] {msg}', flush=True)


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def ensure_runtime(name):
    spec = RUNTIMES[name]
    if spec['check'].exists():
        return
    dest = paths.RUNTIME / name
    dest.mkdir(parents=True, exist_ok=True)
    archive = paths.RUNTIME / Path(spec['url']).name
    if not archive.exists() or sha256(archive) != spec['sha256']:
        log(f'downloading {name} ({spec["url"]})')
        urllib.request.urlretrieve(spec['url'], archive)
    if sha256(archive) != spec['sha256']:
        raise SystemExit(f'{archive.name}: checksum mismatch, refusing to use it')
    log(f'unpacking {name}')
    with tarfile.open(archive) as t:
        try:
            t.extractall(dest, filter='tar')
        except TypeError:           # Python < 3.12 (macOS system python is 3.9)
            t.extractall(dest)
    if not spec['check'].exists():
        raise SystemExit(f'{name}: unexpected archive layout ({spec["check"]} missing)')
    # Downloaded runtimes carry quarantine; strip it so Gatekeeper doesn't stall first launch.
    subprocess.run(['xattr', '-dr', 'com.apple.quarantine', str(dest)], check=False)


def ensure_tools():
    if all((paths.TOOLS / t).exists() for t in NATIVE_TOOLS):
        return
    log('building native helpers (one-time)')
    subprocess.run([str(paths.REPO / 'native/build.sh'), str(paths.TOOLS)], check=True)


# Games needing the DXMT/DXVK stack (32-bit DirectX 11/10) are handed off to exe-metal,
# which composes the Sikarugir Wine + renderer. We expect its binary here (setup copies it).
def exemetal_path():
    return Path.home() / 'Library' / 'Application Support' / 'exe-metal' / 'bin' / 'exe-metal'


def ensure_exemetal():
    p = exemetal_path()
    if not p.exists():
        raise SystemExit(
            'This game needs the DXMT path, which Mac Game Porter hands off to exe-metal.\n'
            'Install exe-metal (https://github.com/navilansanthanakrishnan/exe-metal) and copy its\n'
            f'built binary to:\n  {p}\nThen run this again. (See the README section on DXMT games.)')
    return p


# --- Native DXMT runtime (Sikarugir) -------------------------------------------
# A Wine 11 built from CrossOver sources that exports the winemetal entry points DXMT
# needs and ships DXMT built in, plus the shared frameworks it links against (FreeType,
# GStreamer). Pins mirror the Sikarugir releases the Vapor project ships; bump both the
# URL and its checksum together. This is the self-contained DXMT path (no exe-metal).
SIKARUGIR_DIR = paths.RUNTIME / 'sikarugir'          # wine/ (the Wine) + frameworks/ (dylibs)
SIKARUGIR = {
    'engine': ('https://github.com/Sikarugir-App/Engines/releases/download/v1.0/WS12WineSikarugir11.0_1.tar.xz',
               '67e29fb3d74f363af39c69ba11f9b13a79812c5db07cf4748672658e4a200a0e'),
    'template': ('https://github.com/Sikarugir-App/Template/releases/download/v1.0/Template-1.0.24.tar.xz',
                 '4b5f89eeb9ef139936bdfad33d9b420b05ea4597cb7d63376674f7a8e171321c'),
}


def _extract(archive, dest):
    with tarfile.open(archive) as t:
        try:
            t.extractall(dest, filter='tar')
        except TypeError:                     # Python < 3.12
            t.extractall(dest)


def _download_verified(url, sha, dest):
    if not dest.exists() or sha256(dest) != sha:
        log(f'downloading {Path(url).name}')
        urllib.request.urlretrieve(url, dest)
    if sha256(dest) != sha:
        raise SystemExit(f'{dest.name}: checksum mismatch, refusing to use it')


def ensure_sikarugir():
    """Assemble the Sikarugir Wine (DXMT built in) + the frameworks it needs, cached once.

    Returns SIKARUGIR_DIR with wine/ (bin/wine, lib/wine/... incl. the DXMT d3d11/dxgi and
    winemetal) and frameworks/ (FreeType, GStreamer, the dylibs the Wine links against)."""
    wine = SIKARUGIR_DIR / 'wine'
    fw = SIKARUGIR_DIR / 'frameworks'
    if (wine / 'bin' / 'wine').exists() and fw.exists():
        return SIKARUGIR_DIR
    SIKARUGIR_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=paths.RUNTIME) as t:
        t = Path(t)
        eng = t / Path(SIKARUGIR['engine'][0]).name
        _download_verified(*SIKARUGIR['engine'], eng)
        log('unpacking Sikarugir Wine (DXMT built in)')
        _extract(eng, t)
        bundle = next((p for p in t.glob('**/wswine.bundle') if (p / 'bin' / 'wine').exists()), None)
        if not bundle:
            raise SystemExit('Sikarugir engine: wswine.bundle/bin/wine not found after unpack')
        if wine.exists():
            shutil.rmtree(wine)
        shutil.move(str(bundle), str(wine))

        tpl = t / Path(SIKARUGIR['template'][0]).name
        _download_verified(*SIKARUGIR['template'], tpl)
        log('unpacking Sikarugir frameworks + DXMT renderer')
        _extract(tpl, t)
        app = next((p for p in t.glob('**/*.app') if (p / 'Contents' / 'Frameworks').is_dir()), None)
        if not app:
            raise SystemExit('Sikarugir template: app bundle not found after unpack')
        # Shared dylibs (FreeType, GStreamer, MoltenVK, ...) the Wine links against.
        if fw.exists():
            shutil.rmtree(fw)
        shutil.copytree(app / 'Contents' / 'Frameworks', fw, symlinks=True)
        # The engine ships only Wine's builtin wined3d d3d11; overlay the real DXMT renderer
        # (winemetal.so + DXMT's d3d11/dxgi/d3d10core) from the template onto the engine's wine
        # tree. renderer/dxmt/wine/<arch>/ maps onto wine/lib/wine/<arch>/. Symlinks preserved:
        # dereferencing them yields an engine that looks right but doesn't work.
        rwine = next((p for p in app.glob('**/renderer/dxmt/wine') if p.is_dir()), None)
        if not rwine:
            raise SystemExit('Sikarugir template: renderer/dxmt/wine not found')
        shutil.copytree(rwine, wine / 'lib' / 'wine', dirs_exist_ok=True, symlinks=True)
    # Downloaded bits carry quarantine; strip it so Gatekeeper doesn't stall first launch.
    subprocess.run(['xattr', '-dr', 'com.apple.quarantine', str(SIKARUGIR_DIR)], check=False)
    log('Sikarugir runtime ready')
    return SIKARUGIR_DIR
