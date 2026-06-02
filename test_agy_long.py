from tradingagents.ai_runtime.providers.agy_runtime import AgyRuntime
import time

r = AgyRuntime('gemini-3.5-flash', False, 120)

prompt = (
    "You are a market analyst. Analyze AAPL stock for 2024-01-15.\n\n"
    "Available tools:\n"
    "- get_stock_price(ticker, date)\n"
    "- get_news(ticker, start_date, end_date)\n"
    "- get_fundamentals(ticker)\n\n"
    "You must respond with exactly one JSON object:\n"
    '{\"type\":\"tool_call\",\"tool_calls\":[{\"name\":\"tool_name\",\"args\":{}}]}\n'
    "OR\n"
    '{\"type\":\"final\",\"content\":\"your analysis\"}\n\n'
    "Provide comprehensive technical and fundamental analysis including price trends, "
    "volume, RSI, MACD, moving averages, support/resistance levels, news sentiment, "
    "and earnings outlook. Be thorough and detailed."
)

print("sending prompt...")
t = time.monotonic()
result = r.run_prompt(prompt)
elapsed = time.monotonic() - t
print(f"done in {elapsed:.1f}s")
print("error:", result.error)
print("text[:200]:", (result.text or "")[:200])
