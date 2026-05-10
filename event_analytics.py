import pandas as pd

from collections import Counter
from collections import defaultdict

# ---------------------------------
# LOAD EVENTS
# ---------------------------------

events = pd.read_parquet(
    "market_events.parquet"
)

print()
print("EVENT ANALYTICS")
print()

# ---------------------------------
# EMPTY
# ---------------------------------

if len(events) == 0:

    print("NO EVENTS FOUND")

    exit()

# ---------------------------------
# EVENT COUNTS
# ---------------------------------

event_counts = Counter(

    events['event']
)

# ---------------------------------
# PRINT COUNTS
# ---------------------------------

print("================================")
print("EVENT FREQUENCY")
print("================================")
print()

for event, count in (

    event_counts.items()
):

    print(
        event,
        "| Count:",
        count
    )

# ---------------------------------
# TRANSITIONS
# ---------------------------------

transitions = defaultdict(int)

event_list = list(
    events['event']
)

for i in range(

    1,
    len(event_list)
):

    prev_event = (
        event_list[i - 1]
    )

    current_event = (
        event_list[i]
    )

    transition = (

        prev_event
        +
        " -> "
        +
        current_event
    )

    transitions[
        transition
    ] += 1

# ---------------------------------
# SORT
# ---------------------------------

sorted_transitions = sorted(

    transitions.items(),

    key=lambda x: x[1],

    reverse=True
)

# ---------------------------------
# PRINT
# ---------------------------------

print()
print("================================")
print("TOP EVENT TRANSITIONS")
print("================================")
print()

for transition, count in (

    sorted_transitions[:20]
):

    print(
        transition,
        "| Count:",
        count
    )

# ---------------------------------
# PERSISTENCE
# ---------------------------------

persistence = defaultdict(int)

current_streak = 1

for i in range(

    1,
    len(event_list)
):

    if (

        event_list[i]
        ==
        event_list[i - 1]
    ):

        current_streak += 1

    else:

        persistence[
            event_list[i - 1]
        ] += current_streak

        current_streak = 1

# ---------------------------------
# PRINT
# ---------------------------------

print()
print("================================")
print("EVENT PERSISTENCE")
print("================================")
print()

for event, total in (

    persistence.items()
):

    occurrences = (
        event_counts[event]
    )

    avg_persistence = (

        total
        /
        occurrences
    )

    print(
        event,
        "| Avg Persistence:",
        round(
            avg_persistence,
            2
        )
    )

print()
print("ANALYSIS COMPLETE")
