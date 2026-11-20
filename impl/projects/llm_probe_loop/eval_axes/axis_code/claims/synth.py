def synthesize(view):
    return {"verdict": "some" if view.own["claims"] else "none"}
