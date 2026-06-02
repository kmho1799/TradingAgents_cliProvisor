"""실제 TradingAgents market_analyst 프롬프트 크기 측정 및 agy 테스트"""
import json
import time
import sys
sys.path.insert(0, ".")

from tradingagents.ai_runtime.providers.agy_runtime import AgyRuntime, _HELPER

# cli_client._build_tool_prompt 재현
from tradingagents.agents.utils.agent_utils import get_stock_data, get_indicators

# tool specs 직렬화 (langchain schema)
tool_specs = []
for t in [get_stock_data, get_indicators]:
    try:
        schema = t.args_schema.model_json_schema() if hasattr(t, 'args_schema') and t.args_schema else {}
    except Exception:
        schema = {}
    tool_specs.append({
        "name": getattr(t, 'name', str(t)),
        "description": getattr(t, 'description', ''),
        "parameters": schema,
    })

system_msg = (
    "You are a helpful AI assistant, collaborating with other assistants."
    " Use the provided tools to progress towards answering the question."
    " If you are unable to fully answer, another assistant will help."
    " You have access to the following tools: get_stock_data, get_indicators.\n"
    """You are a trading assistant tasked with analyzing financial markets. Your role is to select the most relevant indicators for a given market condition from the following list. Choose up to 8 indicators that provide complementary insights without redundancy.

Moving Averages: close_50_sma, close_200_sma, close_10_ema
MACD: macd, macds, macdh
Momentum: rsi
Volatility: boll, boll_ub, boll_lb, atr
Volume: vwma

Select indicators that provide diverse and complementary information. Write a very detailed and nuanced report. Make sure to append a Markdown table at the end."""
)

conversation = "Human: Analyze AAPL for 2024-01-15. Provide comprehensive market analysis."

prompt = "\n\n".join([
    f"System: {system_msg}",
    f"Current date: 2024-01-15",
    conversation,
    "You may call tools, but you must respond with exactly one JSON object and no markdown.",
    'If you need tool data: {"type":"tool_call","tool_calls":[{"name":"tool_name","args":{}}]}',
    'If you can answer: {"type":"final","content":"your answer"}',
    "Available tools:",
    json.dumps(tool_specs, ensure_ascii=False),
])

print(f"프롬프트 길이: {len(prompt):,}자")
print(f"프롬프트 처음 200자: {prompt[:200]}")
print()

r = AgyRuntime('gemini-3.5-flash', False, 120)
print("agy 호출 중...")
t = time.monotonic()
result = r.run_prompt(prompt)
elapsed = time.monotonic() - t
print(f"완료: {elapsed:.1f}s")
print(f"error: {result.error}")
print(f"text[:200]: {(result.text or '')[:200]}")
