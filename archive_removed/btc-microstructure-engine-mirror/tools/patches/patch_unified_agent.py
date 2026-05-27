from pathlib import Path

content = Path(
    "unified_behavioral_agent_v1.py"
).read_text()

old_block = '''
            latest = initiative_memory[-1]

            direction = latest["direction"]

            state = latest["state"]

            tests = latest["successful_tests"]
'''

new_block = '''
            memory_df = pd.read_parquet(
                "initiative_memory.parquet"
            )

            latest = memory_df.iloc[-1]

            direction = latest["direction"]

            state = latest["state"]

            tests = latest["successful_tests"]
'''

content = content.replace(
    old_block,
    new_block
)

Path(
    "unified_behavioral_agent_v2.py"
).write_text(content)

print(
    "\\nunified_behavioral_agent_v2.py FIXED\\n"
)
