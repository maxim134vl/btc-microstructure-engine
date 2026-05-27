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
    "BEHAVIORAL SEQUENCE ENGINE"
)

print()

# ---------------------------------
# EMPTY
# ---------------------------------

if len(events) < 3:

    print(
        "NOT ENOUGH EVENTS"
    )

    exit()

# ---------------------------------
# EVENT LIST
# ---------------------------------

event_list = list(
    events['event']
)

# ---------------------------------
# SEQUENCES
# ---------------------------------

sequence_counts = defaultdict(int)

# ---------------------------------
# BUILD CHAINS
# ---------------------------------

for i in range(

    len(event_list) - 2
):

    event_1 = (
        event_list[i]
    )

    event_2 = (
        event_list[i + 1]
    )

    event_3 = (
        event_list[i + 2]
    )

    sequence = (

        event_1
        +
        " -> "
        +
        event_2
        +
        " -> "
        +
        event_3
    )

    sequence_counts[
        sequence
    ] += 1

# ---------------------------------
# SORT
# ---------------------------------

sorted_sequences = sorted(

    sequence_counts.items(),

    key=lambda x: x[1],

    reverse=True
)

# ---------------------------------
# PRINT
# ---------------------------------

print("================================")
print("TOP SEQUENCES")
print("================================")
print()

for sequence, count in (

    sorted_sequences[:20]
):

    print(
        sequence,
        "| Count:",
        count
    )

# ---------------------------------
# TRANSITIONS
# ---------------------------------

transition_matrix = defaultdict(int)

for i in range(

    len(event_list) - 1
):

    current_event = (
        event_list[i]
    )

    next_event = (
        event_list[i + 1]
    )

    transition = (

        current_event
        +
        " -> "
        +
        next_event
    )

    transition_matrix[
        transition
    ] += 1

# ---------------------------------
# PRINT
# ---------------------------------

print()
print("================================")
print("TRANSITION MATRIX")
print("================================")
print()

sorted_transitions = sorted(

    transition_matrix.items(),

    key=lambda x: x[1],

    reverse=True
)

for transition, count in (

    sorted_transitions[:20]
):

    print(
        transition,
        "| Count:",
        count
    )

# ---------------------------------
# PERSISTENT CHAINS
# ---------------------------------

persistent = []

for sequence, count in (

    sequence_counts.items()
):

    if count >= 3:

        persistent.append(
            sequence
        )

# ---------------------------------
# PRINT
# ---------------------------------

print()
print("================================")
print("PERSISTENT SEQUENCES")
print("================================")
print()

if len(persistent) == 0:

    print(
        "NO PERSISTENT CHAINS"
    )

else:

    for seq in persistent:

        print(seq)

print()
print(
    "SEQUENCE ANALYSIS COMPLETE"
)
