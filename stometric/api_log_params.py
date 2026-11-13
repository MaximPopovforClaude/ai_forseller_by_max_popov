"""Bound request diagnostics without ever cutting a serialized JSON document."""
import json


def encode(params, limit=2000):
    text = json.dumps(params, ensure_ascii=False, default=str)
    if len(text) <= limit:
        return text
    
    
    summary = {"_truncated": True, "_characters": len(text),
               "_type": type(params).__name__}
    if isinstance(params, dict):
        summary["_fields"] = len(params)
    elif isinstance(params, (list, tuple)):
        summary["_items"] = len(params)
    return json.dumps(summary, ensure_ascii=False)
