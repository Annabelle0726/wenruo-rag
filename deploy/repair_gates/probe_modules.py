import importlib.util as u
import sys

print("sys.path[0:4]:", sys.path[:4])
for m in ("packaging", "pluggy", "iniconfig", "pygments", "pytest", "pytest_asyncio",
          "numpy", "requests", "elasticsearch", "redis", "yaml", "tiktoken", "litellm"):
    spec = u.find_spec(m)
    print(f"{m:16s}", spec.origin if spec else "ABSENT")
