from pathlib import Path

content = Path(
    "stopping_volume_replay_v1.py"
).read_text()

# =====================================
# FIX ADDPLOTS COLORS
# =====================================

content = content.replace(
"""
mpf.make_addplot(
        stopping_series,
        type='scatter',
        marker='^',
        markersize=80
    )
""",
"""
mpf.make_addplot(
        stopping_series,
        type='scatter',
        marker='^',
        markersize=80,
        color='blue'
    )
"""
)

content = content.replace(
"""
mpf.make_addplot(
        test_series,
        type='scatter',
        marker='o',
        markersize=100
    )
""",
"""
mpf.make_addplot(
        test_series,
        type='scatter',
        marker='o',
        markersize=100,
        color='orange'
    )
"""
)

content = content.replace(
"""
mpf.make_addplot(
        confirmation_series,
        type='scatter',
        marker='s',
        markersize=130
    )
""",
"""
mpf.make_addplot(
        confirmation_series,
        type='scatter',
        marker='s',
        markersize=130,
        color='green'
    )
"""
)

content = content.replace(
"""
mpf.make_addplot(
        failed_series,
        type='scatter',
        marker='x',
        markersize=120
    )
""",
"""
mpf.make_addplot(
        failed_series,
        type='scatter',
        marker='x',
        markersize=120,
        color='red'
    )
"""
)

# =====================================
# FIX LEGEND COLORS
# =====================================

content = content.replace(
"""
ax.plot(
    [],
    [],
    marker='^',
    linestyle='None',
    markersize=10,
    label='Stopping Volume'
)
""",
"""
ax.plot(
    [],
    [],
    marker='^',
    linestyle='None',
    markersize=10,
    color='blue',
    label='Stopping Volume'
)
"""
)

content = content.replace(
"""
ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    label='Тест'
)
""",
"""
ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    color='orange',
    label='Тест'
)
"""
)

content = content.replace(
"""
ax.plot(
    [],
    [],
    marker='s',
    linestyle='None',
    markersize=10,
    label='Подтверждение'
)
""",
"""
ax.plot(
    [],
    [],
    marker='s',
    linestyle='None',
    markersize=10,
    color='green',
    label='Подтверждение'
)
"""
)

content = content.replace(
"""
ax.plot(
    [],
    [],
    marker='x',
    linestyle='None',
    markersize=10,
    label='Провал'
)
""",
"""
ax.plot(
    [],
    [],
    marker='x',
    linestyle='None',
    markersize=10,
    color='red',
    label='Провал'
)
"""
)

Path(
    "stopping_volume_replay_v2.py"
).write_text(content)

print(
    "\\nstopping_volume_replay_v2.py CREATED\\n"
)
