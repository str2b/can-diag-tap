# diag_filter

Shared filter engine used by `can-diag-trace` and `can-diag-console`.

This package defines the JSON schema used by `--filter`.

## Filter File Format

```json
{
  "mode": "whitelist",
  "rules": [
    {
      "layer": "can",
      "id": "0x12F1",
      "payload": "^0210.*"
    },
    {
      "layer": "kwp",
      "src": "0xF1",
      "service": "0x31",
      "payload": "^3101"
    }
  ]
}
```

Notes:

- `mode` supports `whitelist` and `blacklist`.
- Rule fields are ANDed.
- `payload` is treated as regex over uppercase hex payload text.
- `layer` is required per rule and depends on message type made available by each tool.

Behavior summary:

- `whitelist`: drop messages unless at least one matching rule exists for that message layer.
- `blacklist`: keep messages unless a rule matches for that message layer.
- Rule constraints are ANDed (all listed fields in one rule must match).
- `payload` regex is evaluated against uppercase hex payload text.

Matching details:

- ID-like fields are compared case-insensitively as normalized strings (`0x...` style is supported).
- Rules are evaluated only within the same `layer` as the current message.
- If no rules exist for a message layer, that message is not filtered by default.

Setup:

```sh
cd diag_filter
python -m venv .venv
# activate the virtual environment in your shell
python -m pip install --upgrade pip
pip install -e .
```
