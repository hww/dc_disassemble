# DC Script Disassembler

A toolset for disassembling **DC scripts** (Naughty Dog / Sony `sid32` format used in *Uncharted 4* and *The Last of Us Part I / II*) into readable assembly listings with SID resolution, struct dumps, state-script parsing, and script-lambda disassembly.

---

## Features

- **Bytecode disassembly** for `script-lambda` and `function` types
- **State-script parsing** — full tree: `StateScript` → `SsDeclarationList` → `SsOptions` → `SsStateTable` → `SsOnBlock` → `SsTrack` → `SsLambda` → `ScriptLambda`
- **SID resolution** via `sids.txt` and `.dci` export files
- **Relocation table** support (bitmap-based pointer slots)
- **Struct dumps** with heuristics for floats, offsets, SIDs, and pointers
- **Blood-effect-map-entry** parsing
- **Primitive types**: `boolean`, `int32`, `float`, `quat`, `point`
- **Function reference search** (`--find-refs`)
- **Batch processing** — sequential and multi-threaded wrappers

---

## Repository Layout

| File | Description |
| ------ | ------------- |
| `dc_core.py` | Core library: SID generation, native table, readers, `DcHeader`, `DcDefinition`, `DcDescriptor`, instruction map |
| `dc_disassemble_v3.py` | Main disassembler (sid32 / UC4 / T1X) |
| `disall_v3.sh` | Sequential batch disassembler |
| `disall_v3_mtreads.py` | Parallel batch disassembler (wrapper) |
| `disall_v3_mtreads.sh` | One-liner parallel launcher |
| `disall_v2.sh` | Legacy wrapper (v2 script) |
| `sids.txt` | SID name table (`<hex_hash> <name>`) |
| `*.dci` | Export lists (auto-loaded next to the input `.bin`) |

---

## Requirements

- **Python 3.8+**
- **Bash** (for shell wrappers)
- `xargs` with `-P` support (GNU findutils)

No external Python dependencies.

---

## Installation

```bash
git clone https://github.com/<your-user>/dc-disassembler.git
cd dc-disassembler
chmod +x disall_v3.sh disall_v3_mtreads.py disall_v3_mtreads.sh
```

Make sure `sids.txt` is in the same directory as the scripts — it is loaded automatically from the script's own folder.

---

## Usage

### Single file

```bash
python3 dc_disassemble_v3.py --dump-structs path/to/script.bin
```

### Useful flags

| Flag | Description |
| ------ | ------------- |
| `--dump-structs` | Recursively dump bodies of structures using heuristics |
| `--max-structs N` | Limit the number of dumped structs (`0` = unlimited, default `3`) |
| `--only-script-lambda`, `-l` | Only disassemble `script-lambda` and `function` |
| `--type-filter HEX`, `-t` | Filter by type ID |
| `--name-filter NAME`, `-n` | Filter by name (or `0x...` for name ID) |
| `--find-refs NAME` | Find all references to a function by name |
| `--no-reloc` | Skip reading the relocation table |
| `--verbose`, `-v` | Verbose output |

### Batch — sequential

```bash
./disall_v3.sh [input_dir] [output_dir] [extra flags...]
```

Examples:

```bash
./disall_v3.sh                              # ./  → ./asm
./disall_v3.sh dc1                          # dc1 → ./asm
./disall_v3.sh dc1 out_asm --max-structs 0  # no struct limit
./disall_v3.sh dc1 out_asm --verbose
```

### Batch — parallel

```bash
./disall_v3_mtreads.py <input_dir> <output_dir> <parallel> [extra flags...]
```

Example (from `disall_v3_mtreads.sh`):

```bash
python3 disall_v3_mtreads.py dc1 asm 8 --max-structs 0
```

Each `.bin` produces a corresponding `.asm`. Failed runs leave a `.err` sidecar file next to the output.

---

## SID Table Format (`sids.txt`)

```
# <hashid> <string>
5D95B08B blood-effect-map-entry
2DB90AD2 npc-blood-effect-map
B78A7E53 body-part
```

- One entry per line
- Lines starting with `#` are comments
- Inline comments with `#` are stripped
- Hash must be 8 or 16 hex chars (optionally prefixed with `0x`)

If a `.dci` file with the same base name as the input `.bin` exists, its `(export ...)` block is loaded automatically into the local symbol table.

---

## Output Structure

For a `script-lambda` / `function` definition:

```
Name: my-func  NameId: 0x12345678
Type: script-lambda  TypeId: 0x9E1B3A2C
Defn: 0x00001234: Body at: 0x00002340:
DcDescriptor: ...
Code: 0x00002350: Data: 0x00002480:
0x00002350: 0C 05 00 01  loadImm r5, 0x0001     # r5 = 1
0x00002354: 01 06 05 07  intAdd  r6, r5, r7     # r6 = r5 + r7
...
```

For a `state-script`, the full hierarchy is expanded as a nested tree.

For `blood-effect-map-entry`:

```
  body: nameId=0x... (name) data_offset=0x... typeId=0x... (type)
    data at 0x... {
      [000] 0x...: count=... | off=0x... | sid=0x...
    }
```

---

## Common SID Constants

Registered in `dc_core.py`:

- Types: `vector`, `string`, `float`, `angle`, `state`, `direction`, `color`, `boolean`, `vec4`, `script-lambda`, `function`, `int32`, `quat`, `point`, `lambda`, `method`, `type`
- Base types: `pointer`, `number`, `integer`, `sinteger`, `uinteger`, `int8/16/32/64`, `uint8/16/32/64`
- Structural: `top`, `top-level`, `define`, `defun`, `defvar`, `defconst`, `macro`, `defmacro`, `structure`, `basic`, `symbol`, `array`, `inline-array`, `darray`, `symbol-array`, `map`, `map-32`, `state-script`
- Game: `process`, `process-tree`, `process-drawable`, `entity`, `game-obj`, `handle`, `dead-pool`, `active-pool`, `actor`, `player`, `enemy`, `item`, `weapon`, `projectile`, `trigger`, `checkpoint`, `camera`, `light`
- Animation: `animation`, `idle`, `walk`, `run`, `jump`, `attack`, `damage`, `death`, `spawn`, `despawn`, `interact`
- Audio / UI: `sound`, `music`, `audio`, `ui-element`, `button`, `menu`, `hud`, `timer`, `counter`, `event`, `callback`

Any unknown ID can still be resolved at runtime via `sids.txt`.

---

## How It Works

### DC file layout (sid32)

```
┌──────────────────────────────┐
│ DcHeader (28 bytes)          │  magic, version, textSize,
│                              │  stringsOffset, always1,
│                              │  numEntries, defTableOff
├──────────────────────────────┤
│ text section                 │  code, data, strings
├──────────────────────────────┤
│ reloc table (bitmap)         │  one bit per 4/8-byte slot
├──────────────────────────────┤
│ DcDefinition[] (12 bytes ea) │  nameId, typeId, offset
└──────────────────────────────┘
```

### Heuristics in `--dump-structs`

For each 4-byte word:

1. In `native_table` / `local_table` → **SID**
2. Bit set in reloc bitmap → **pointer**
3. Bit pattern decodes to a "nice" float → **float**
4. `0 < v < textSize` and `v % 4 == 0` → **offset**
5. `v < 0x10000` → **int**
6. Otherwise → **hex int**

### Instruction set

Opcodes `0x00`–`0x4A` are mapped in `dc_core.inst_map`. Each has an optional `print_<name>` handler in `dc_core.py` that produces the mnemonic, operands, and a comment with the decoded semantics.

Branch instructions (`branch`, `branchIf`, `branchIfNot`) compute the target as `code + offset * 4` relative to the descriptor start.

---

## Known Limitations

- `array`, `inline-array`, `darray`, `symbol-array`, `map`, `map-32` are recognized but the parser is **TODO** — they fall back to `--dump-structs`.
- Heuristics can misclassify ambiguous 4-byte values (e.g. small integers vs. small floats).
- Only the `sid32` format is fully supported. Legacy 64-bit-hash formats are not decoded.
- No emitter for re-assemblable bytecode.

---

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success (or no input files found) |
| `1` | Missing script, missing input directory, or one or more files failed |

When batch jobs fail, failed file names are listed at the end.

---

## License

Specify your license here (e.g. MIT).

---

## Credits

Reverse-engineering research on Naughty Dog's DC scripting VM. Instruction semantics and structure layouts are the result of community analysis of retail builds of *Uncharted 4: A Thief's End* and *The Last of Us Part I*.
