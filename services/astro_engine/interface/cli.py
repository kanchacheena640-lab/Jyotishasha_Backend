from datetime import timedelta
from services.astro_engine.data_provider.ephemeris_provider import get_current_datetime_ist
from services.astro_engine.core.rashi_pair_engine import get_pair_status
from services.astro_engine.core.event_finder import (
    find_last_same_rashi_window,
    find_next_same_rashi_window
)


def format_dt(dt):
    if not dt:
        return "Not found"
    return dt.strftime("%Y-%m-%d %H:%M")


def duration(entry, exit):
    if not entry or not exit:
        return "N/A"

    diff = exit - entry
    total_hours = diff.total_seconds() / 3600

    days = int(total_hours // 24)
    hours = int(total_hours % 24)

    return f"{days}d {hours}h"


def run_cli():
    print("\n🔥 Astro Engine CLI (Advanced)\n")

    VALID = ["Sun","Moon","Mars","Mercury","Jupiter","Venus","Saturn","Rahu","Ketu"]

    print("Available planets:")
    print(", ".join(VALID))

    # Input
    p1 = input("\nSelect Planet 1: ").strip().capitalize()
    p2 = input("Select Planet 2: ").strip().capitalize()

    if p1 not in VALID or p2 not in VALID:
        print("❌ Invalid planet name")
        return

    current_date = get_current_datetime_ist()

    # Initial windows
    last_entry, last_exit = find_last_same_rashi_window(p1, p2, current_date)
    next_entry, next_exit = find_next_same_rashi_window(p1, p2, current_date)

    # Handle current active case
    if last_entry and last_exit and last_entry <= current_date <= last_exit:
        next_entry, next_exit = find_next_same_rashi_window(
            p1, p2, last_exit + timedelta(days=1)
        )

    while True:
        print("\n============================")
        print("Date:", current_date.strftime("%Y-%m-%d"))

        status = get_pair_status(p1, p2, current_date)

        print(f"\n{p1} → {status['rashi1']} ({status['degree1']}°)")
        print(f"{p2} → {status['rashi2']} ({status['degree2']}°)")

        print("\nSame Rashi:", "✅ YES" if status["same_rashi"] else "❌ NO")

        if status["same_rashi"]:
            print("\n🔥 CURRENT CONJUNCTION ACTIVE")

        # LAST
        print("\n🕓 LAST CONJUNCTION:")
        print("Entered:", format_dt(last_entry))
        print("Exited :", format_dt(last_exit))
        print("Duration:", duration(last_entry, last_exit))

        # NEXT
        print("\n🔮 NEXT CONJUNCTION:")
        print("Entered:", format_dt(next_entry))
        print("Exited :", format_dt(next_exit))
        print("Duration:", duration(next_entry, next_exit))

        # Controls
        print("\nControls:")
        print("n → next conjunction")
        print("p → previous conjunction")
        print("q → quit")

        cmd = input("\nEnter command: ").lower()

        # -----------------------
        # NEXT CONJUNCTION
        # -----------------------
        if cmd in ["n", "next"]:
            if next_entry:
                current_date = next_entry

                # current becomes LAST
                last_entry, last_exit = next_entry, next_exit

                # skip current → find true next
                next_entry, next_exit = find_next_same_rashi_window(
                    p1, p2, next_exit + timedelta(days=1)
                )

        # -----------------------
        # PREVIOUS CONJUNCTION
        # -----------------------
        elif cmd in ["p", "prev"]:
            if last_entry:
                # 🔥 if current is same as last → go one more back
                if last_entry <= current_date <= last_exit:
                    prev_entry, prev_exit = find_last_same_rashi_window(
                        p1, p2, last_entry - timedelta(days=1)
                    )
                else:
                    prev_entry, prev_exit = last_entry, last_exit

                current_date = prev_entry

                # update windows
                next_entry, next_exit = last_entry, last_exit
                last_entry, last_exit = find_last_same_rashi_window(
                    p1, p2, prev_entry - timedelta(days=1)
                )

        # QUIT
        elif cmd == "q":
            break

        # INVALID
        else:
            print("❌ Invalid command")


if __name__ == "__main__":
    run_cli()