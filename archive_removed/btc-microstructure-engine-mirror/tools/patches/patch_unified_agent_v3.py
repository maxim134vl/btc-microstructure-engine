from pathlib import Path

content = Path(
    "unified_behavioral_agent_v2.py"
).read_text()

content = content.replace(
    'if len(initiative_memory) > 0:',
    'if len(memory_df) > 0:'
)

Path(
    "unified_behavioral_agent_v3.py"
).write_text(content)

print(
    "\\nunified_behavioral_agent_v3.py CREATED\\n"
)
