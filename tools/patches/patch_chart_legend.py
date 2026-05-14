from pathlib import Path

content = Path(
    "behavioral_replay_m15_v1.py"
).read_text()

old = '''
mpf.plot(
    ohlc,
    type='candle',
    style='charles',
    title='Поведенческий Replay Аукциона',
    volume=False,
    addplot=apds,
    figsize=(20, 12),
    tight_layout=True
)

print("\\n================================")
print("ЛЕГЕНДА")
print("================================\\n")

print("▲ = Инициатива")
print("○ = Тест")
print("■ = Защита")
print("◆ = Поглощение")
print("✖ = Ложный пробой / rejection")
'''

new = '''
fig, axlist = mpf.plot(
    ohlc,
    type='candle',
    style='charles',
    title='Поведенческий Replay Аукциона',
    volume=False,
    addplot=apds,
    figsize=(20, 12),
    tight_layout=True,
    returnfig=True
)

ax = axlist[0]

ax.plot(
    [],
    [],
    marker='^',
    linestyle='None',
    markersize=10,
    label='Инициатива'
)

ax.plot(
    [],
    [],
    marker='o',
    linestyle='None',
    markersize=10,
    label='Тест'
)

ax.plot(
    [],
    [],
    marker='s',
    linestyle='None',
    markersize=10,
    label='Защита'
)

ax.plot(
    [],
    [],
    marker='D',
    linestyle='None',
    markersize=10,
    label='Поглощение'
)

ax.plot(
    [],
    [],
    marker='x',
    linestyle='None',
    markersize=10,
    label='Ложный пробой'
)

ax.legend(
    loc='upper left',
    fontsize=12
)

mpf.show()
'''

content = content.replace(
    old,
    new
)

Path(
    "behavioral_replay_m15_v2.py"
).write_text(content)

print(
    "\\nbehavioral_replay_m15_v2.py CREATED\\n"
)
