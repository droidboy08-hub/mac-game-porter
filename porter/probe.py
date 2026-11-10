"""Decide which Wine runtime and DirectX->Metal renderer a game needs.

Game Porting Toolkit (the original runtime) pairs an old Wine (7.7) with Apple's
D3DMetal, which is excellent for 64-bit DirectX 12 but cannot run 32-bit games at
all (D3DMetal is 64-bit only) and is weak on some DirectX 11 titles. That is why a
32-bit DX11 game such as BioShock 2 Remastered launches, plays its intro, then dies.

This module reads a game's PE header for its CPU bitness and which Direct3D version
it links against, then picks a runtime + renderer that can actually run it:

  64-bit, DX12         -> gptk + d3dmetal   (Apple's fast path; the only DX12 backend)
  64-bit, DX11/DX10    -> gptk + d3dmetal   (works; DXMT is the fallback)
  32-bit, DX11/DX10    -> sikarugir + dxmt  (D3DMetal is 64-bit only; DXMT handles 32-bit)
  any,    DX9 only     -> sikarugir + dxvk  (DX9 over Vulkan)

The runtime/renderer facts below were confirmed on Apple Silicon; the notes record
the dead ends so we steer around them instead of rediscovering each one.
"""
import mmap
from pathlib import Path

# PE machine types (COFF header).
_MACHINE_I386 = 0x014C
_MACHINE_AMD64 = 0x8664
# Optional-header magic.
_PE32 = 0x10B
_PE32_PLUS = 0x20B


class PEInfo:
    """What the executable header tells us: 32- vs 64-bit and the DirectX it uses."""

    def __init__(self, bits, directx):
        self.bits = bits                 # 32, 64, or None if unreadable
        self.directx = directx           # sorted list like ['d3d9', 'd3d11']

    @property
    def dx_versions(self):
        """Numeric DirectX versions present, e.g. {9, 11}."""
        return {int(d[3:]) for d in self.directx if d[3:].isdigit()}

    def __repr__(self):
        return f'PEInfo(bits={self.bits}, directx={self.directx})'


# Direct3D import DLLs we look for, newest first (a game that pulls in d3d12 is a
# DX12 game even if it also references d3d11 for a fallback path).
_D3D_DLLS = (b'd3d12', b'd3d11', b'd3d10', b'd3d9')


def read_pe(exe_path):
    """Read bitness and Direct3D references straight from the PE file.

    Bitness comes from the COFF machine field (authoritative). DirectX is detected by
    scanning for the import DLL names: a full import-table walk is overkill here and the
    names appear verbatim in the import directory, so a bounded byte scan is enough and
    matches how game.py already sniffs the binary for controller support.
    """
    path = Path(exe_path)
    try:
        with open(path, 'rb') as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as m:
            if m[:2] != b'MZ':
                return PEInfo(None, [])                      # not a PE at all
            e_lfanew = int.from_bytes(m[0x3C:0x40], 'little')
            if e_lfanew + 6 > len(m) or m[e_lfanew:e_lfanew + 4] != b'PE\x00\x00':
                return PEInfo(None, [])                      # truncated / not a real PE
            machine = int.from_bytes(m[e_lfanew + 4:e_lfanew + 6], 'little')
            bits = {_MACHINE_I386: 32, _MACHINE_AMD64: 64}.get(machine)
            lower = m[:].lower()
            directx = [dll.decode() for dll in _D3D_DLLS if dll + b'.dll' in lower]
            return PEInfo(bits, sorted(set(directx)))
    except (OSError, ValueError):
        return PEInfo(None, [])


# --- Runtime + renderer catalog ------------------------------------------------
# Each runtime is a Wine build; each renderer a DirectX->Metal translator applied on
# top. 'winemetal' marks the builds that export the entry points DXMT needs (only the
# Sikarugir build does). These facts are what make the pairing rules below correct.

RUNTIME_FACTS = {
    'gptk': {
        'wine': '7.7', 'winemetal': False, 'win32': False,
        'note': "Apple's Game Porting Toolkit; bundles D3DMetal. 64-bit only, no DXMT.",
    },
    'sikarugir': {
        'wine': '11.0', 'winemetal': True, 'win32': True,
        'note': 'CrossOver-sourced Wine that exports winemetal; the only build DXMT runs on. '
                'Runs 32-bit via wine32on64, which also avoids the GPTK vprot assertion.',
    },
}

RENDERER_FACTS = {
    'd3dmetal': {'apis': {10, 11, 12}, 'bits': {64},
                 'note': "Apple's D3DMetal. Only backend with DX12. 64-bit only."},
    'dxmt': {'apis': {10, 11}, 'bits': {32, 64},
             'note': 'Open-source DX10/11 -> Metal. Handles 32-bit. Needs a winemetal runtime.'},
    'dxvk': {'apis': {9, 10, 11}, 'bits': {32, 64},
             'note': 'DX -> Vulkan -> Metal (MoltenVK). An extra hop, but renders what the others refuse.'},
}


class Stack:
    """A chosen runtime + renderer, with the reason, for the launcher and the log."""

    def __init__(self, runtime, renderer, reason):
        self.runtime = runtime
        self.renderer = renderer
        self.reason = reason

    def to_conf(self):
        return f'RUNTIME={self.runtime!r}\nRENDERER={self.renderer!r}\n'

    def __repr__(self):
        return f'Stack(runtime={self.runtime!r}, renderer={self.renderer!r})'


def choose_stack(pe):
    """Pick the runtime+renderer for a probed executable.

    The decisive facts: D3DMetal is 64-bit only, so a 32-bit game can never use it;
    DX12 exists only on D3DMetal; and DXMT needs the Sikarugir (winemetal) runtime.
    """
    dx = pe.dx_versions
    bits = pe.bits or 64                        # assume 64-bit when the header was unreadable

    if bits == 64 and 12 in dx:
        return Stack('gptk', 'd3dmetal', '64-bit DirectX 12: D3DMetal is the only DX12 backend')
    if bits == 64 and (11 in dx or 10 in dx):
        return Stack('gptk', 'd3dmetal', '64-bit DirectX 11: D3DMetal handles it on the fast path')
    if bits == 32 and (11 in dx or 10 in dx):
        return Stack('sikarugir', 'dxmt',
                     '32-bit DirectX 11/10: D3DMetal is 64-bit only, so DXMT on the Sikarugir runtime')
    if dx and max(dx) <= 9:
        return Stack('sikarugir', 'dxvk', 'DirectX 9: translated through Vulkan (DXVK/MoltenVK)')
    # No Direct3D found, or an unknown mix: GPTK for 64-bit, Sikarugir for 32-bit.
    if bits == 32:
        return Stack('sikarugir', 'dxmt', '32-bit: GPTK cannot run 32-bit games, so the Sikarugir runtime')
    return Stack('gptk', 'd3dmetal', 'defaulting to the Game Porting Toolkit path')


def probe(exe_path):
    """Convenience: read the PE and choose a stack in one call."""
    pe = read_pe(exe_path)
    return pe, choose_stack(pe)
