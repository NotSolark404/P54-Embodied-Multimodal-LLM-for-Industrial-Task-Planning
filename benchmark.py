import time
import sys
import os
sys.path.insert(0, '.')

from llm_backend.custom_LLM_parser import parse_instruction

instructions = [
    "pick up the red block and place it in the left tray",
    "place the red block to the left of the blue block",
    "grab the yellow block and drop it in the right tray",
    "move the blue block near the workstation",
    "locate the green block",
    "pick up the blue block and place it in the right tray",
    "move the green block to the right of the workstation",
    "find the yellow block",
    "place the red block next to the workstation",
    "pick up the green block",
]

results = []
print(f"\n{'─'*60}")
print(f"  LLM Latency Benchmark — GPT-4o — {len(instructions)} instructions")
print(f"{'─'*60}")

for instr in instructions:
    t0 = time.perf_counter()
    parse_instruction(instr)
    ms = (time.perf_counter() - t0) * 1000
    results.append(ms)
    print(f"  {ms:6.0f}ms  {instr[:50]}")

results.sort()
mean = sum(results) / len(results)
p95  = results[int(len(results) * 0.95)]
mn   = results[0]
mx   = results[-1]

print(f"\n{'─'*60}")
print(f"  Mean:  {mean:.0f}ms")
print(f"  P95:   {p95:.0f}ms")
print(f"  Min:   {mn:.0f}ms")
print(f"  Max:   {mx:.0f}ms")
print(f"{'─'*60}\n")