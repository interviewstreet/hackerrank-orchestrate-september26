from langgraph.graph import StateGraph, START, END
from code.src.state import AgentState
from code.src.data.repository import DataRepository
from code.src.graph import nodes
from code.src.graph.routing import route_after_evaluation


def build_financial_agent_graph(repo: DataRepository):
    builder = StateGraph(AgentState)

    # Add nodes with injected DataRepository
    builder.add_node("load_request", lambda state: nodes.load_request_node(state, repo))
    builder.add_node("load_user_context", lambda state: nodes.load_user_context_node(state, repo))
    builder.add_node("load_financial_data", lambda state: nodes.load_financial_data_node(state, repo))
    builder.add_node("resolve_images", lambda state: nodes.resolve_images_node(state, repo))
    builder.add_node("resolve_messages", nodes.resolve_messages_node)
    builder.add_node("resolve_event_lifecycle", nodes.resolve_event_lifecycle_node)
    builder.add_node("normalize_events", lambda state: nodes.normalize_events_node(state, repo))
    builder.add_node("convert_currencies", lambda state: nodes.convert_currencies_node(state, repo))
    builder.add_node("validate_resolved_data", nodes.validate_resolved_data_node)
    builder.add_node("build_financial_state", nodes.build_financial_state_node)
    builder.add_node("generate_base_forecast", nodes.generate_base_forecast_node)
    builder.add_node("calculate_baseline_capacity", nodes.calculate_baseline_capacity_node)
    builder.add_node("generate_candidate_plans", nodes.generate_candidate_plans_node)
    builder.add_node("evaluate_plans", nodes.evaluate_plans_node)

    builder.add_node("generate_change_sets", nodes.generate_change_sets_node)
    builder.add_node("evaluate_change_sets", nodes.evaluate_change_sets_node)

    builder.add_node("select_decision", nodes.select_decision_node)
    builder.add_node("generate_explanation", nodes.generate_explanation_node)
    builder.add_node("validate_output", nodes.validate_output_node)

    # Define linear and conditional edges
    builder.add_edge(START, "load_request")
    builder.add_edge("load_request", "load_user_context")
    builder.add_edge("load_user_context", "load_financial_data")
    builder.add_edge("load_financial_data", "resolve_images")
    builder.add_edge("resolve_images", "resolve_messages")
    builder.add_edge("resolve_messages", "resolve_event_lifecycle")
    builder.add_edge("resolve_event_lifecycle", "normalize_events")
    builder.add_edge("normalize_events", "convert_currencies")
    builder.add_edge("convert_currencies", "validate_resolved_data")
    builder.add_edge("validate_resolved_data", "build_financial_state")
    builder.add_edge("build_financial_state", "generate_base_forecast")
    builder.add_edge("generate_base_forecast", "calculate_baseline_capacity")
    builder.add_edge("calculate_baseline_capacity", "generate_candidate_plans")
    builder.add_edge("generate_candidate_plans", "evaluate_plans")

    # Conditional branching
    builder.add_conditional_edges(
        "evaluate_plans",
        route_after_evaluation,
        {
            "select_decision": "select_decision",
            "generate_change_sets": "generate_change_sets",
        },
    )

    builder.add_edge("generate_change_sets", "evaluate_change_sets")
    builder.add_edge("evaluate_change_sets", "select_decision")

    builder.add_edge("select_decision", "generate_explanation")
    builder.add_edge("generate_explanation", "validate_output")
    builder.add_edge("validate_output", END)

    return builder.compile()
