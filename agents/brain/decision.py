import json


def analyze_response(response):

    try:
        data = json.loads(response)

    except json.JSONDecodeError:
        return {
            "action": "answer",
            "content": response
        }


    if "tool" in data:

        return {
            "action": "tool",
            "tool": data["tool"],
            "arguments": data.get("arguments", {})
        }


    return {
        "action": "answer",
        "content": data.get("content", response)
    }