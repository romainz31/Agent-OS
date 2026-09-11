### life_forget
Oublie une information personnelle uniquement après une demande explicite de Romain.

Input schema for tool_args:
{
  "type": "object",
  "properties": {
    "record_ids": {"type": "array", "items": {"type": "string"}},
    "query": {"type": "string"},
    "reason": {"type": "string"}
  },
  "additionalProperties": false
}

Si plusieurs souvenirs correspondent, demande lequel supprimer.

Exemple :
```json
{
  "tool_name": "life_forget",
  "tool_args": {
    "query": "souvenir test",
    "reason": "demande explicite de Romain"
  }
}
```
