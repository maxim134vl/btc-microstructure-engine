import pandas as pd

from collections import defaultdict

# ---------------------------------
# LOAD EVENTS
# ---------------------------------

events = pd.read_parquet(
    "market_events.parquet"
)

print()
print(
    "STATE PERSISTENCE ENGINE"
)

print()

# ---------------------------------
# EMPTY
# ---------------------------------

if len(events) == 0:

    print(
        "NO EVENTS FOUND"
    )

    exit()

# ---------------------------------
# EVENT LIST
# ---------------------------------

event_list = list(
    events['event']
)

# ---------------------------------
# PERSISTENCE STORAGE
# ---------------------------------

durations = defaultdict(list)

# ---------------------------------
# INITIALIZE
# ---------------------------------

current_event = event_list[0]

current_duration = 1

# ---------------------------------
# LOOP
# ---------------------------------

for i in range(

    1,

    len(event_list)
):

    event = event_list[i]

    # SAME STATE

    if event == current_event:

        current_duration += 1

    # NEW STATE

    else:

        durations[
            current_event
        ].append(
            current_duration
        )

        current_event = event

        current_duration = 1

# ---------------------------------
# FINAL
# ---------------------------------

durations[
    current_event
].append(
    current_duration
)

# ---------------------------------
# PRINT
# ---------------------------------

print("================================")
print("STATE DURATIONS")
print("================================")
print()

for state, values in (

    durations.items()
):

    avg_duration = (

        sum(values)
        /
        len(values)
    )

    max_duration = max(
        values
    )

    min_duration = min(
        values
    )

    print(
        "STATE:",
        state
    )

    print(
        "Occurrences:",
        len(values)
    )

    print(
        "Average Duration:",
        round(
            avg_duration,
            2
        )
    )

    print(
        "Max Duration:",
        max_duration
    )

    print(
        "Min Duration:",
        min_duration
    )

    print()

# ---------------------------------
# EXTREME STATES
# ---------------------------------

print("================================")
print("EXTREME PERSISTENCE")
print("================================")
print()

for state, values in (

    durations.items()
):

    extreme = [

        x for x in values

        if x >= 5
    ]

    if len(extreme) == 0:

        continue

    print(
        state,
        "| Extreme Episodes:",
        len(extreme)
    )

    print(
        "Durations:",
        extreme
    )

    print()

print(
    "PERSISTENCE ANALYSIS COMPLETE"
)
