"""Windows 명령줄 길이 한계 테스트 (32767자 초과)"""
import time, sys
sys.path.insert(0, ".")
from tradingagents.ai_runtime.providers.agy_runtime import AgyRuntime

r = AgyRuntime('gemini-3.5-flash', False, 60)

# 실제 get_stock_data 반환값 시뮬레이션: CSV 데이터 (~50KB)
csv_data = "Date,Open,High,Low,Close,Volume\n" + "\n".join(
    f"2024-{(i//30)+1:02d}-{(i%30)+1:02d},150.{i%100},152.{i%100},149.{i%100},151.{i%100},{1000000+i*1000}"
    for i in range(500)  # 500일치 주가 데이터
)

prompt = (
    "Analyze this stock data and respond with JSON:\n"
    f"Stock CSV data:\n{csv_data}\n\n"
    'Respond: {"type":"final","content":"brief analysis"}'
)

print(f"프롬프트 길이: {len(prompt):,}자")
print(f"Windows 명령줄 한계: 32,767자")
print(f"한계 초과: {len(prompt) > 32767}")
print()
print("agy 호출 중...")
t = time.monotonic()
result = r.run_prompt(prompt)
elapsed = time.monotonic() - t
print(f"완료: {elapsed:.1f}s")
print(f"error: {result.error}")
print(f"text[:100]: {(result.text or '')[:100]}")
