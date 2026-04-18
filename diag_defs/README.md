# diag_defs

Shared definitions parser used by both `can-diag-trace` and `can-diag-console`.

This package defines the JSON schema used by `--defs`.

## Custom Definitions (JSON)

The decoder maps service bytes using a JSON definition file.
For a given service ID, you can provide either a single definition object or a list of candidate objects.

When a list is provided, candidates are ranked by `src` and `tgt` against message context. A precise `src`/`tgt` match is preferred over a generic fallback.

```json
{
	"services": {
		"0x50": [
			{
				"name": "FictionalPositiveResponse_AA",
				"src": "0xAA",
				"args": {
					"default": [
						{ "name": "status", "length": 1, "enum": {"0x01": "ok"} }
					]
				}
			},
			{
				"name": "FictionalPositiveResponse_Generic",
				"args": {
					"default": [
						{ "name": "status", "length": 1 }
					]
				}
			}
		],
		"0x99": {
			"name": "FictionalServiceKey",
			"args": {
				"default": [
					{
						"name": "fictionalId",
						"length": 1,
						"enum": {"0x0A": "getStatus", "0x0B": "getSecurity"}
					},
					{
						"switch_on": "fictionalId",
						"mux": {
							"0x0A": [
								{"name": "fictionalSubStatus", "length": 1, "enum": {"0x01": "active", "0x00": "inactive"}}
							],
							"0x0B": [
								{"name": "fictionalSecurity", "length": 4}
							]
						}
					},
					{"name": "fictionalData", "length": -1}
				]
			}
		}
	}
}
```

Notes:

- Service keys can be hex (`"0x99"`) or decimal (`"153"`).
- `switch_on` + `mux` enables conditional parsing based on a prior field value.
- `enum` supports exact values and ranges (for example `"0x1F0A-0x1F0F": "group"`).

Interpretation of the example above:

1. Handler selection can be targeted precisely (`0x50` with `src: "0xAA"`) before falling back to the generic `0x50` definition.
2. If the service ID is `0x99`, it maps to `FictionalServiceKey`.
3. Parameter layout is evaluated in order, including conditional branches.
4. Conditional muxing uses `switch_on` to choose the next argument list from `mux`.

### Enum Range Parsing

The `enum` dictionary supports:

- Exact numeric values (for example `"0x0A": "foo"`)
- Numeric ranges (for example `"0x1F0A-0x1F0F": "group"`)

Setup:

```sh
cd diag_defs
python -m venv .venv
# activate the virtual environment in your shell
python -m pip install --upgrade pip
pip install -e .
```