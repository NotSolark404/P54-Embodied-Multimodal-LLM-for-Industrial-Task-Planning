with open('llm_backend/LLM_eval/eval_report.py', 'r') as f:
    content = f.read()

old = """                s = "✓" if row["fully_correct"] else ("✗" if row["parse_success"] else "!")
                print(f"  [{case.id}] {case.instruction[:48]:<48} {s}  {row['latency_ms']:6.0f}ms")"""

new = """                s = "✓" if row["fully_correct"] else ("✗" if row["parse_success"] else "!")
                instr   = case.instruction[:48].ljust(48)
                latency = row["latency_ms"]
                print(f"  [{case.id}] {instr} {s}  {latency:6.0f}ms")"""

content = content.replace(old, new)

with open('llm_backend/LLM_eval/eval_report.py', 'w') as f:
    f.write(content)
print("Done")
