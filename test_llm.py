"""LLM surface-area test — expose raw output types so we know what the wrapper sees.

Run from project root:  python test_llm.py
"""

import sys, os, json
sys.path.insert(0, os.path.dirname(__file__))

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from core.chat_model import VertexAILLM
from langchain.agents import create_agent




SEP = "\n" + "=" * 60 + "\n"

# ── 1. Vanilla LLM call ────────────────────────────────────────────
print(SEP + "TEST 1 — vanilla llm.invoke()")
llm = VertexAILLM()
result1 = llm.invoke([HumanMessage(content="Say one sentence like Rick from Rick and Morty.")])
print(f"  type : {type(result1)}")
print(f"  .content type : {type(result1.content)}")
print(f"  .content value: {result1.content!r}")

# ── 2. LLM with structured output ─────────────────────────────────
print(SEP + "TEST 2 — llm.with_structured_output(Schema)")

class RickQuote(BaseModel):
    quote: str = Field(description="One Rick-style sentence")
    catchphrase: str = Field(description="Wubba lubba or similar")

structured_llm = llm.with_structured_output(RickQuote)
result2 = structured_llm.invoke([HumanMessage(content="Give me a Rick and Morty style quote.")])
print(f"  type : {type(result2)}")

# with_structured_output returns AIMessage with JSON content — parse it
parsed = RickQuote(**json.loads(result2.content))
print(f"  .quote      : {parsed.quote!r}")
print(f"  .catchphrase: {parsed.catchphrase!r}")

# ── 3. create_agent — no tools, just invoke ─────────────────
print(SEP + "TEST 3 — create_agent (no tools)")

agent3 = create_agent(
    model=VertexAILLM(),
    tools=[],
    prompt="You are Rick Sanchez. Keep replies to one sentence.",
)
result3 = agent3.invoke({"messages": [HumanMessage(content="Hi.")]})
print(f"  type           : {type(result3)}")
print(f"  keys           : {list(result3.keys()) if isinstance(result3, dict) else 'N/A'}")
last_msg3 = result3["messages"][-1]
print(f"  last msg type  : {type(last_msg3)}")
print(f"  last .content  : {last_msg3.content!r}")

# ── 4. create_agent — with a calc tool ──────────────────────
print(SEP + "TEST 4 — create_agent (with calc tool)")

@tool
def multiply(a: float, b: float) -> float:
    """Multiply two numbers and return the result."""
    return a * b

agent4 = create_agent(
    model=VertexAILLM(),
    tools=[multiply],
    prompt="You are Rick Sanchez. Use the multiply tool when asked to calculate.",
)
result4 = agent4.invoke({"messages": [HumanMessage(content="Morty, what is 7 times 6? Use the tool.")]})
print(f"  type           : {type(result4)}")
print(f"  all messages:")
for i, m in enumerate(result4["messages"]):
    print(f"    [{i}] type={type(m).__name__}  content={m.content!r}")
last_msg4 = result4["messages"][-1]
print(f"  last .content  : {last_msg4.content!r}")

print(SEP + "ALL TESTS PASSED ✓")
