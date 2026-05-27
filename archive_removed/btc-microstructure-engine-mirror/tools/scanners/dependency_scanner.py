from pathlib import Path
import re

ROOT = Path(".")

py_files = list(
    ROOT.glob("*.py")
)

read_map = {}
write_map = {}

# =====================================
# SCAN
# =====================================

for file in py_files:

    text = file.read_text(
        encoding="utf-8"
    )

    reads = re.findall(
        r"read_parquet\s*\(\s*['\"]([^'\"]+)",
        text
    )

    writes = re.findall(
        r"to_parquet\s*\(\s*['\"]([^'\"]+)",
        text
    )

    read_map[file.name] = reads

    write_map[file.name] = writes

# =====================================
# OUTPUT
# =====================================

print()
print("=" * 60)
print("PARQUET DEPENDENCY MAP")
print("=" * 60)
print()

for engine in sorted(read_map):

    print(engine)

    print("  READS:")

    for item in read_map[engine]:

        print(
            "   -",
            item
        )

    print()

    print("  WRITES:")

    for item in write_map[engine]:

        print(
            "   -",
            item
        )

    print()
