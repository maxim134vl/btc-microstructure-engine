import os
import time

print("\nCANONICAL PIPELINE STARTED\n")

# =====================================
# LOOP
# =====================================

while True:

    print("=" * 60)

    print("RUNNING CANONICAL PIPELINE")

    print("=" * 60)

    print()

    # =================================
    # CANDLE GEOMETRY
    # =================================

    print("1. CANDLE GEOMETRY")

    os.system(
        "python3 candle_geometry_engine_v2.py"
    )

    print()

    # =================================
    # VOLUME LOCALIZATION
    # =================================

    print("2. VOLUME LOCALIZATION")

    os.system(
        "python3 volume_localization_engine_v2.py"
    )

    print()

    # =================================
    # TEST RECOGNITION
    # =================================

    print("3. TEST RECOGNITION")

    os.system(
        "python3 test_recognition_engine_v1.py"
    )

    print()

    # =================================
    # DEFENDED LIQUIDITY
    # =================================

    print("4. DEFENDED LIQUIDITY")

    os.system(
        "python3 defended_liquidity_engine_v1.py"
    )

    print()

    # =================================
    # PERCEPTION INTEGRATION
    # =================================

    print("5. PERCEPTION INTEGRATION")

    os.system(
        "python3 perception_context_integration_v1.py"
    )

    print()

    # =================================
    # CONTEXTUAL MEMORY
    # =================================

    print("6. CONTEXTUAL MEMORY")

    os.system(
        "python3 contextual_memory_loader_v2.py"
    )

    print()

    print("=" * 60)

    print("PIPELINE COMPLETE")

    print("=" * 60)

    print()

    # =================================
    # WAIT
    # =================================

    time.sleep(30)
