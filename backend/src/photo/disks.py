"""Enumerate drives the user can install to, with free space."""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

Kind = Literal["fixed", "removable", "network", "unknown"]

# Filesystems on Linux that are real storage rather than kernel or virtual mounts.
_LINUX_FS = {
    "ext2",
    "ext3",
    "ext4",
    "xfs",
    "btrfs",
    "f2fs",
    "zfs",
    "ntfs",
    "ntfs3",
    "exfat",
    "vfat",
    "fuseblk",
}


@dataclass(frozen=True, slots=True)
class Disk:
    root: str
    label: str
    kind: Kind
    total: int
    free: int

    def to_api(self) -> dict[str, Any]:
        return asdict(self)


def _windows_disks() -> list[Disk]:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined,unused-ignore]
    kinds: dict[int, Kind] = {2: "removable", 3: "fixed", 4: "network"}
    disks: list[Disk] = []
    mask = kernel32.GetLogicalDrives()
    for i in range(26):
        if not mask & (1 << i):
            continue
        root = f"{chr(65 + i)}:\\"
        drive_type = kernel32.GetDriveTypeW(root)
        if drive_type not in kinds:  # skip CD-ROM, RAM disks, no-root
            continue
        try:
            usage = shutil.disk_usage(root)
        except OSError:
            continue  # empty card reader slot, disconnected share
        name = ctypes.create_unicode_buffer(261)
        ok = kernel32.GetVolumeInformationW(
            wintypes.LPCWSTR(root), name, 261, None, None, None, None, 0
        )
        disks.append(
            Disk(root, name.value if ok else "", kinds[drive_type], usage.total, usage.free)
        )
    return disks


def _linux_disks() -> list[Disk]:
    seen: set[str] = set()
    disks: list[Disk] = []
    try:
        mounts = Path("/proc/mounts").read_text().splitlines()
    except OSError:
        mounts = []
    for line in mounts:
        parts = line.split()
        if len(parts) < 3:
            continue
        device, mount, fstype = parts[0], parts[1].replace("\\040", " "), parts[2]
        if fstype not in _LINUX_FS or device in seen:
            continue
        if mount.startswith(("/boot", "/snap", "/var/lib/docker")):
            continue
        try:
            usage = shutil.disk_usage(mount)
        except OSError:
            continue
        seen.add(device)
        kind: Kind = "removable" if mount.startswith(("/media", "/run/media")) else "fixed"
        disks.append(Disk(mount, Path(mount).name or "/", kind, usage.total, usage.free))
    if not disks:
        usage = shutil.disk_usage("/")
        disks.append(Disk("/", "/", "fixed", usage.total, usage.free))
    return disks


def list_disks() -> list[Disk]:
    if sys.platform == "win32":
        return _windows_disks()
    return _linux_disks()


def disk_for(path: Path, disks: list[Disk]) -> Disk | None:
    """The disk holding ``path`` (longest matching mount point)."""
    p = str(path.resolve())
    if os.name == "nt":
        p = p.lower()
    best: Disk | None = None
    for d in disks:
        root = d.root.lower() if os.name == "nt" else d.root
        if p.startswith(root) and (best is None or len(d.root) > len(best.root)):
            best = d
    return best


def free_space(path: Path) -> int:
    probe = path
    while not probe.exists():
        if probe.parent == probe:
            return 0
        probe = probe.parent
    return shutil.disk_usage(probe).free
