### **Code Zip**

Code Zip captures their agent design, architecture, libraries, prompt structure, retrieval strategy, guardrails, and engineering quality.

The code rubric is the signal that looks at what the participant actually shipped during the 24 hours. The judge receives the full code and README, and scores across four dimensions.

> **We reward only what is observable in the source code.** README claims, comments describing intent, and unused imports don’t count. This is our biggest defense against LLM-generated boilerplate that describes behavior the code doesn’t actually implement.

| **Dimension**             | **Weight** | **What it measures**                                                                                                                      |
| ------------------------- | ---------: | ----------------------------------------------------------------------------------------------------------------------------------------- |
| **Agent architecture**    |        30% | Is this an agent, or a hardcoded workflow with LLM calls? Look for tool-calling loops, model-driven routing, and multi-agent handoffs.    |
| **Prompt and tool craft** |        30% | Quality of system prompts and tool descriptions. Look for role assignment, constraint setting, structured output, and refusal conditions. |
| **Agent robustness**      |        25% | Guardrails, retries, max-iteration caps, output validation, and RAG pipeline quality.                                                     |
| **Engineering rigor**     |        15% | Multi-file modularity, type hints, secrets handled via environment variables, and function size.                                          |
