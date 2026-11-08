from photo.hardware import Arch, arch_from_compute_cap, parse_nvidia_smi, primary_gpu


def test_parse_nvidia_smi() -> None:
    out = (
        "0, NVIDIA GeForce RTX 5080, 16303, 617.42, 12.0\n"
        "1, NVIDIA GeForce GTX 1060, 6144, 617.42, 6.1\n"
    )
    gpus = parse_nvidia_smi(out)
    assert [g.name for g in gpus] == ["NVIDIA GeForce RTX 5080", "NVIDIA GeForce GTX 1060"]
    assert gpus[0].arch is Arch.BLACKWELL
    assert gpus[0].vram_gb == 15.9
    assert gpus[0].driver_major == 617


def test_parse_ignores_garbage() -> None:
    assert parse_nvidia_smi("No devices were found\n") == []
    assert parse_nvidia_smi("0, X, [N/A], 1.0, 8.9") == []


def test_arch_mapping() -> None:
    assert arch_from_compute_cap("8.9") is Arch.ADA
    assert arch_from_compute_cap("12.0") is Arch.BLACKWELL
    assert arch_from_compute_cap("10.0") is Arch.BLACKWELL
    assert arch_from_compute_cap("8.6") is Arch.AMPERE
    assert arch_from_compute_cap("7.5") is Arch.OLDER
    assert arch_from_compute_cap("") is Arch.UNKNOWN


def test_primary_gpu_prefers_supported_then_vram() -> None:
    gpus = parse_nvidia_smi(
        "0, Old Big, 24576, 617.0, 7.5\n"
        "1, RTX 4060, 8188, 617.0, 8.9\n"
        "2, RTX 4090, 24564, 617.0, 8.9"
    )
    best = primary_gpu(gpus)
    assert best is not None and best.index == 2
    assert primary_gpu([]) is None
