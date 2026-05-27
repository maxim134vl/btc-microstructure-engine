from pathlib import Path

content = Path(
    "buy_structure_replay_v1.py"
).read_text()

content = content.replace(
    '"15min"',
    '"1h"'
)

Path(
    "buy_structure_replay_h1.py"
).write_text(content)

print(
    "\\nbuy_structure_replay_h1.py CREATED\\n"
)
