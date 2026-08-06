def analyze_response(response):

    response = response.lower()

    if "addition" in response or "calcul" in response:
        return {
    "action": "tool",
    "tool": "addition",
    "arguments": {
        "a": 5,
        "b": 3
    }
}

    return {
        "action": "answer",
        "content": response
    }