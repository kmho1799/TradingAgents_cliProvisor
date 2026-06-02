import time, sys
sys.path.insert(0, ".")
from tradingagents.ai_runtime.providers.agy_runtime import AgyRuntime

r = AgyRuntime('gemini-3.5-flash', False, 60)
csv_data = "Date,Open,High,Low,Close,Volume\n" + "\n".join(
    f"2024-{(i//30)+1:02d}-{(i%30)+1:02d},150.{i%100},152.{i%100},149.{i%100},151.{i%100},{1000000+i*1000}"
    for i in range(1500)
)
prompt = f"Analyze:\n{csv_data}\nRespond: " + '{"type":"final","content":"analysis"}'
print(f"len={len(prompt):,}  over_limit={len(prompt) > 32767}")
t = time.monotonic()
result = r.run_prompt(prompt)
print(f"done={time.monotonic()-t:.1f}s error={result.error}")
print(f"text={repr((result.text or '')[:80])}")
