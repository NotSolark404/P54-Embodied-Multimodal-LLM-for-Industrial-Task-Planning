"""
demo.py - Sprint 1 Demo for LLM Instruction Parser
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEMO_INSTRUCTIONS = [
    "pick up the red block",
    "locate the yellow block",
    "place the blue cube in the left tray",
    "move the green block to the right of the workstation",
    "grab the red block and drop it near the blue tray",
    "put that thing over there",
]

SEPARATOR = "─" * 60


def print_result(instruction, result):
    dumped = result.model_dump(mode="json")
    print(f"\n📝  Instruction : {instruction}")
    print(f"⚙️   Action      : {dumped['action']}")
    print(f"📦  Object      : {dumped['object_target']}")
    print(f"📍  Destination : {dumped['destination'] or '—'}")
    print(f"↔️   Spatial     : {dumped['spatial_relation'] or '—'}")
    print(f"🎯  Confidence  : {dumped['confidence']}")
    if dumped["notes"]:
        print(f"📌  Notes       : {dumped['notes']}")
    print(SEPARATOR)


def run_demo(parse_fn):
    print("\n" + "═" * 60)
    print("  Multimodal LLM for Industrial Task Planning")
    print("  LLM Module — Sprint 1 Demo")
    print("═" * 60)

    for instruction in DEMO_INSTRUCTIONS:
        print(SEPARATOR)
        try:
            result = parse_fn(instruction)
            print_result(instruction, result)
        except Exception as e:
            print(f"\n❌  FAILED: {instruction}")
            print(f"    Error: {e}")
            print(SEPARATOR)


def run_interactive(parse_fn):
    print("\n" + "═" * 60)
    print("  LLM Module — Interactive Mode")
    print("  Type an instruction and press Enter.")
    print("  Type 'quit' to exit.")
    print("═" * 60 + "\n")

    while True:
        try:
            instruction = input("🤖  Instruction: ").strip()
            if instruction.lower() in ("quit", "exit", "q"):
                print("Goodbye!")
                break
            if not instruction:
                continue
            result = parse_fn(instruction)
            print_result(instruction, result)
        except KeyboardInterrupt:
            print("\nGoodbye!")
            break
        except Exception as e:
            print(f"❌  Error: {e}\n")


def main():
    from parser import parse_instruction

    if "--interactive" in sys.argv or "-i" in sys.argv:
        run_interactive(parse_instruction)
    else:
        run_demo(parse_instruction)


if __name__ == "__main__":
    main()