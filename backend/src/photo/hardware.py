"""GPU detection via ``nvidia-smi``.

Deliberately avoids importing torch: the app server must start fast and must be able
to diagnose a machine where the engine environment is not installed yet.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from enum import StrEnum

# CUDA 13.0 wheels (what the engine is locked to) need driver >= 580.
MIN_DRIVER_MAJOR = 580


class Arch(StrEnum):
    BLACKWELL = "blackwell"  # RTX 50xx, sm_120 (and datacenter sm_100)
    ADA = "ada"  # RTX 40xx, sm_89
    AMPERE = "ampere"  # RTX 30xx, sm_86 — works, not officially supported
    OLDER = "older"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Gpu:
    index: int
    name: str
    vram_mib: int
    driver: str
    compute_cap: str

    @property
    def vram_gb(self) -> float:
        return round(self.vram_mib / 1024, 1)

    @property
    def arch(self) -> Arch:
        return arch_from_compute_cap(self.compute_cap)

    @property
    def driver_major(self) -> int:
        try:
            return int(self.driver.split(".", 1)[0])
        except ValueError:
            return 0

    @property
    def supported(self) -> bool:
        return self.arch in (Arch.BLACKWELL, Arch.ADA)


def arch_from_compute_cap(cap: str) -> Arch:
    try:
        major_s, minor_s = cap.strip().split(".", 1)
        major, minor = int(major_s), int(minor_s)
    except ValueError:
        return Arch.UNKNOWN
    if major >= 10:
        return Arch.BLACKWELL
    if (major, minor) == (8, 9):
        return Arch.ADA
    if major == 8:
        return Arch.AMPERE
    return Arch.OLDER


_QUERY = "index,name,memory.total,driver_version,compute_cap"


def parse_nvidia_smi(output: str) -> list[Gpu]:
    gpus: list[Gpu] = []
    for line in output.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 5:
            continue
        idx, name, mem, driver, cap = parts
        try:
            gpus.append(Gpu(int(idx), name, int(float(mem)), driver, cap))
        except ValueError:
            continue
    return gpus


def detect_gpus(timeout_s: float = 10.0) -> list[Gpu]:
    exe = shutil.which("nvidia-smi")
    if exe is None:
        return []
    try:
        proc = subprocess.run(  # noqa: S603 — fixed argv, no shell
            [exe, f"--query-gpu={_QUERY}", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    return parse_nvidia_smi(proc.stdout)


def primary_gpu(gpus: list[Gpu]) -> Gpu | None:
    """The GPU we generate on: the supported card with the most VRAM."""
    if not gpus:
        return None
    return max(gpus, key=lambda g: (g.supported, g.vram_mib))
