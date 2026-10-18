"""NVIDIA architecture support, reviewed 2026-10-16.

Sources: https://developer.nvidia.com/cuda-gpus and
https://docs.nvidia.com/cuda/cuda-toolkit-release-notes/index.html
Active architectures have a supported series, not a predicted final version.
"""

ARCHITECTURES = {
    "3.5": ("Kepler", "11.8"),
    "3.7": ("Kepler", "11.8"),
    "5.0": ("Maxwell", "12.9"),
    "5.2": ("Maxwell", "12.9"),
    "5.3": ("Maxwell", "12.9"),
    "6.0": ("Pascal", "12.9"),
    "6.1": ("Pascal", "12.9"),
    "6.2": ("Pascal", "12.9"),
    "7.0": ("Volta", "12.9"),
    "7.2": ("Volta", "12.9"),
    "7.5": ("Turing", "13.x（仍受支持）"),
    "8.0": ("Ampere", "13.x（仍受支持）"),
    "8.6": ("Ampere", "13.x（仍受支持）"),
    "8.7": ("Ampere", "13.x（仍受支持）"),
    "8.9": ("Ada Lovelace", "13.x（仍受支持）"),
    "9.0": ("Hopper", "13.x（仍受支持）"),
    "10.0": ("Blackwell", "13.x（仍受支持）"),
    "10.3": ("Blackwell", "13.x（仍受支持）"),
    "12.0": ("Blackwell", "13.x（仍受支持）"),
    "12.1": ("Blackwell", "13.x（仍受支持）"),
}


def architecture_support(capability):
    architecture, cuda = ARCHITECTURES.get(capability, (None, None))
    return {"architecture": architecture, "cuda_arch_max": cuda}
