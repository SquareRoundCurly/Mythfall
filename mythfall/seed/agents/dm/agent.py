def on_message(context):
    return context.run_llm()


def on_handoff(context):
    return context.run_llm()
