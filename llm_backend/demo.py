"""
demo.py
-------
Sprint demo for the LLM Instruction Parser.
Runs a fixed set of example instructions through the parser and prints results.

Usage:
    python demo.py                  # batch demo
    python demo.py --interactive    # interactive mode
    LLM_BACKEND=gemini python demo.py
"""

import sys
import os

# Ensure the package root is on the path when run as a script
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

DEMO_INSTRUCTIONS = [
    "pick up the red block",
    "locate the yellow block",
    "place the blue cube in the left tray",
    "move the green block to the right of the workstation",
    "grab the red block and drop it near the blue tray",
    "put that thing over there",
]

SEPARATOR = "-" * 60


def print_result(instruction, result):
    dumped = result.model_dump(mode="json")
    print(f"\n  Instruction : {instruction}")
    print(f"  Action      : {dumped['action']}")
    print(f"  Object      : {dumped['object_target']}")
    print(f"  Destination : {dumped['destination'] or '-'}")
    print(f"  Spatial     : {dumped['spatial_relation'] or '-'}")
    print(f"  Confidence  : {dumped['confidence']}")
    if dumped["notes"]:
        print(f"  Notes       : {dumped['notes']}")
    print(SEPARATOR)


def run_demo(parse_fn):
    backend = os.getenv("LLM_BACKEND", "openai").upper()
    print("\n" + "=" * 60)
    print("  Multimodal LLM for Industrial Task Planning")
    print(f"  LLM Module Demo  [{backend} backend]")
    print("=" * 60)

    for instruction in DEMO_INSTRUCTIONS:
        print(SEPARATOR)
        try:
            result = parse_fn(instruction)
            print_result(instruction, result)
        except Exception as e:
            print(f"\n  FAILED: {instruction}")
            print(f"  Error: {e}")
            print(SEPARATOR)


def run_interactive(parse_fn):
    backend = os.getenv("LLM_BACKEND", "openai").upper()
    print("\n" + "=" * 60)
    print(f"  LLM Module -- Interactive Mode  [{backend} backend]")
    print("  Type an instruction and press Enter.")
    print("  Type 'quit' to exit.")
    print("=" * 60 + "\n")

    while True:
        try:
            instruction = input("  Instruction: ").strip()
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
            print(f"  Error: {e}\n")


def main():
    from .custom_LLM_parser import parse_instruction  # flat import -- works when run as script

    if "--interactive" in sys.argv or "-i" in sys.argv:
        run_interactive(parse_instruction)
    else:
        run_demo(parse_instruction)


if __name__ == "__main__":
    main()