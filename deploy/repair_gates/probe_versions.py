import importlib.metadata as md

for pkg in ("packaging", "pygments", "pluggy", "iniconfig", "pytest", "pytest-asyncio", "numpy"):
    try:
        print(f"{pkg:16s} {md.version(pkg)}")
    except Exception as exc:  # noqa: BLE001
        print(f"{pkg:16s} ABSENT ({type(exc).__name__})")
