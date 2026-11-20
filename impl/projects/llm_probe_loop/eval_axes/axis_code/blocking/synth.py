def synthesize(view):
    return {"verdict": "has_blocking" if any(i["blocking"] for i in view.own["items"]) else "none"}
