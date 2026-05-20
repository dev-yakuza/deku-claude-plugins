# CONFIG

**SDD Configuration Management**

Manage SDD settings stored in `.github/.sdd-config`.

## Command Parsing:

Parse the arguments from `$1` onwards:
- No arguments → **Show current config**
- `--skip-review=<values>` → **Set skip-review**
- `--skip-review=` (empty value) → **Reset skip-review**

## Show Current Config:

1. Read `.github/.sdd-config`
   - If file doesn't exist → report "No config set. Using defaults (all reviews enabled)."
2. Display current settings in a readable format:
   ```
   SDD Config (.github/.sdd-config)
   ─────────────────────────────────
   skip-review: analyze, design, implement
   ```
3. Show a summary of what each skipped review means:
   | Value | Skipped Review |
   |-------|---------------|
   | `analyze` | User confirmation after analyze stage (AI review still runs) |
   | `design` | User confirmation after design stage (AI review still runs) |
   | `implement` | User confirmation at the implement plan stage (3-0). Steps 3-1 through 3-4 are `self_only` and have no user prompt to skip. |
   | `pr` | User confirmation at PR Final review (3-5) |
   | `qa` | Manual QA execution after the test stage |

## Set skip-review:

1. Validate the values — allowed values: `analyze`, `design`, `implement`, `pr`, `qa`
   - If any invalid value is found → report error with the invalid value and list allowed values
2. Write to `.github/.sdd-config`:
   ```
   skip-review: <comma-separated values>
   ```
3. Confirm the setting was saved and show what reviews will be skipped

## Reset skip-review:

1. Remove the `skip-review` line from `.github/.sdd-config` (or delete the file if it's the only setting)
2. Confirm: "skip-review reset. All reviews are now enabled."
