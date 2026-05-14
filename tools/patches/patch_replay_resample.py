from pathlib import Path

content = Path(
    "historical_behavioral_replay_backtest_v1.py"
).read_text()

content = content.replace(
    '"1H"',
    '"1h"'
)

Path(
    "historical_behavioral_replay_backtest_v2.py"
).write_text(content)

print(
    "\\nhistorical_behavioral_replay_backtest_v2.py CREATED\\n"
)
