#!/usr/bin/python3
"""dc_core.py — стабильные компоненты DC-дизассемблера."""

import struct
import re

#
## Глобальные таблицы (объявляются ДО констант)
#

native_table = {}
import_table = {}
local_table  = {}

ALLIGN = 4
stats_table = {}

#
## StringId Generation
#

def create_table(poly):
    init = 0
    l = [0] * 256
    for i in range(256):
        t = init ^ (i << 24)
        for j in range(8):
            mask = 1 << 31
            if (mask & t) != 0:
                t = (t << 1) ^ poly
            else:
                t = (t << 1)
        l[i] = t & 0xffffffff
    return l

crc32_table = create_table(0x04c11db7)

def crc32(s, init=0):
    crc = init
    if s:
        for c in s:
            crc = (crc32_table[((crc >> 24) ^ ord(c)) & 0xff] ^ (crc << 8)) & 0xffffffff
    return crc

def fnv1a_64(s):
    fnv = 0xcbf29ce484222325
    for c in s:
        fnv = ((ord(c) ^ fnv) * 0x100000001b3) & 0xffffffffffffffff
    return fnv

def StringId(s):
    crc32("array" + s)
    crc32("(array" + s + ")")
    crc32("inline-array" + s)
    crc32("(inline-array" + s + ")")
    return crc32(s)

def register_sid(name):
    """Вычисляет StringId, добавляет в native_table, возвращает хэш."""
    sid = StringId(name)
    native_table[sid] = name
    return sid

#
## SID-константы — автоматически регистрируются в native_table
#

vector_id            = register_sid('vector')
string_id            = register_sid('string')
float_id             = register_sid('float')
angle_id             = register_sid('angle')
state_id             = register_sid('state')
direction_id         = register_sid('direction')
color_id             = register_sid('color')
boolean_id           = register_sid('boolean')
vec4_id              = register_sid('vec4')
script_lambda_id     = register_sid('script-lambda')
function_id          = register_sid('function')
int32_id             = register_sid('int32')
quat_id              = register_sid('quat')
point_id             = register_sid('point')
lambda_id            = register_sid('lambda')
method_id            = register_sid('method')
type_id              = register_sid('type')

# Базовые типы
pointer_id           = register_sid('pointer')
number_id            = register_sid('number')
integer_id           = register_sid('integer')
sinteger_id          = register_sid('sinteger')
uinteger_id          = register_sid('uinteger')
int8_id              = register_sid('int8')
int16_id             = register_sid('int16')
int64_id             = register_sid('int64')
uint8_id             = register_sid('uint8')
uint16_id            = register_sid('uint16')
uint32_id            = register_sid('uint32')
uint64_id            = register_sid('uint64')

# Структурные типы
top_id               = register_sid('top')
top_level_id         = register_sid('top-level')
define_id            = register_sid('define')
defun_id             = register_sid('defun')
defvar_id            = register_sid('defvar')
defconst_id          = register_sid('defconst')
macro_id             = register_sid('macro')
defmacro_id          = register_sid('defmacro')
structure_id         = register_sid('structure')
basic_id             = register_sid('basic')
symbol_id            = register_sid('symbol')
array_id             = register_sid('array')
inline_array_id      = register_sid('inline-array')
darray_id            = register_sid('darray')
symbol_array_id      = register_sid('symbol-array')
map_id               = register_sid('map')
map_32_id            = register_sid('map-32')
state_script_id      = register_sid('state-script')

# Игровые типы
process_id           = register_sid('process')
process_tree_id      = register_sid('process-tree')
process_drawable_id  = register_sid('process-drawable')
entity_id            = register_sid('entity')
game_obj_id          = register_sid('game-obj')
handle_id            = register_sid('handle')
dead_pool_id         = register_sid('dead-pool')
active_pool_id       = register_sid('active-pool')

# Векторы
vector3_id           = register_sid('vector3')
vector4_id           = register_sid('vector4')
matrix3_id           = register_sid('matrix3')
matrix4_id           = register_sid('matrix4')
transform_id         = register_sid('transform')
quaternion_id        = register_sid('quaternion')
vec3_id              = register_sid('vec3')

# Графика
texture_id           = register_sid('texture')
material_id          = register_sid('material')
mesh_id              = register_sid('mesh')
sprite_id            = register_sid('sprite')
font_id              = register_sid('font')

# Игровая логика
actor_id             = register_sid('actor')
player_id            = register_sid('player')
enemy_id             = register_sid('enemy')
item_id              = register_sid('item')
weapon_id            = register_sid('weapon')
projectile_id        = register_sid('projectile')
trigger_id           = register_sid('trigger')
checkpoint_id        = register_sid('checkpoint')
camera_id            = register_sid('camera')
light_id             = register_sid('light')

# Анимации
animation_id         = register_sid('animation')
idle_id              = register_sid('idle')
walk_id              = register_sid('walk')
run_id               = register_sid('run')
jump_id              = register_sid('jump')
attack_id            = register_sid('attack')
damage_id            = register_sid('damage')
death_id             = register_sid('death')
spawn_id             = register_sid('spawn')
despawn_id           = register_sid('despawn')
interact_id          = register_sid('interact')

# Звук / UI / утилиты
sound_id             = register_sid('sound')
music_id             = register_sid('music')
audio_id             = register_sid('audio')
ui_element_id        = register_sid('ui-element')
button_id            = register_sid('button')
menu_id              = register_sid('menu')
hud_id               = register_sid('hud')
timer_id             = register_sid('timer')
counter_id           = register_sid('counter')
event_id             = register_sid('event')
callback_id          = register_sid('callback')

#
## Helpers
#

def safe_seek(fp, offset, size=4):
    fp.seek(0, 2)
    file_size = fp.tell()
    if offset < 0 or offset + size > file_size:
        raise ValueError(f"offset 0x{offset:X} (size {size}) out of file (size 0x{file_size:X})")
    fp.seek(offset)

def read_u32(fp):
    return int.from_bytes(fp.read(4), byteorder='big')

def read_i32(fp):
    return int.from_bytes(fp.read(4), byteorder='big', signed=True)

def read_u64(fp):
    return int.from_bytes(fp.read(8), byteorder='big')

def read_i64(fp):
    return int.from_bytes(fp.read(8), byteorder='big', signed=True)

def read_float(fp):
    s = fp.read(4)
    return struct.unpack('>f', s)[0]

def read_u16(fp):
    return int.from_bytes(fp.read(2), byteorder='big')

def read_i16(fp):
    return int.from_bytes(fp.read(2), byteorder='big', signed=True)

def dump(fp, offset, size=32, prefix="; "):
    try:
        saved = fp.tell()
        safe_seek(fp, offset, size)
        data = fp.read(size)
        fp.seek(saved)
    except Exception:
        return
    print(f"{prefix}Dump at 0x{offset:08X}:")
    for i in range(0, len(data), 16):
        chunk = data[i:i+16]
        hex_str = ' '.join(f"{b:02X}" for b in chunk)
        ascii_str = ''.join(chr(b) if 32 <= b <= 126 else '.' for b in chunk)
        print(f"{prefix}0x{offset+i:08X}: {hex_str:<47} |{ascii_str}|")

def dump_line(fp, offset, size=32):
    try:
        saved = fp.tell()
        safe_seek(fp, offset, size)
        data = fp.read(size)
        fp.seek(saved)
    except Exception:
        return
    print(hex(offset), " ", end="")
    for b in data:
        print("{:02X} ".format(b), end="")
    print()

#
## DC File Structures
#

class DcDescriptor:
    def __init__(self, fp):
        self.desOffset = fp.tell()
        self.start     = read_u32(fp)
        self.end       = read_u32(fp)
        self.type      = read_u32(fp)
        self.size      = read_u32(fp)
        self.data_size = self.size - (self.end - self.start) - 8
        print("DcDescriptor: Offset: 0x{:04X} DescSize:{} Start 0x{:04X}  End: 0x{:04X}:".format(
            self.desOffset, self.start - self.desOffset, self.start, self.end))
        save_pos = fp.tell()
        print("DcDescDump", end="")
        dump_line(fp, self.desOffset, self.start - self.desOffset)
        fp.seek(save_pos)

class DcDefinition:
    """DCEntry — 12 байт в sid32-формате (UC4/T1X)."""
    def __init__(self, fp):
        self.defOffset = fp.tell()
        self.nameId    = read_u32(fp)
        self.typeId    = read_u32(fp)
        self.offset    = read_u32(fp)

class DcHeader:
    """Заголовок DC-файла (sid32-формат, 28 байт)."""
    def __init__(self, fp):
        self.magic         = fp.read(4)
        self.version       = read_u32(fp)
        self.textSize      = read_u32(fp)
        self.stringsOffset = read_u32(fp)
        self.always1       = read_u32(fp)
        self.numEntries    = read_u32(fp)
        self.defTableOff   = read_u32(fp)

#
## Instruction Decoder
#

inst_map = {
    0x00: "return",
    0x01: "intAdd", 0x02: "intSub", 0x03: "intMul", 0x04: "intDiv",
    0x05: "floatAdd", 0x06: "floatSub", 0x07: "floatMul", 0x08: "floatDiv",
    0x09: "loadStaticInt", 0x0A: "loadStaticFloat", 0x0B: "loadStaticPointer",
    0x0C: "loadImm", 0x0D: "loadInt", 0x0E: "loadFloat", 0x0F: "loadPointer",
    0x10: "storeInt", 0x11: "storeFloat", 0x12: "storePointer",
    0x13: "lookupInt", 0x14: "lookupFloat", 0x15: "lookupPointer",
    0x16: "moveInt", 0x17: "moveFloat", 0x18: "movePointer",
    0x19: "castInteger", 0x1A: "castFloat",
    0x1B: "call", 0x1C: "callFf",
    0x1D: "cmpEqual", 0x1E: "cmpGt", 0x1F: "cmpGtEqual",
    0x20: "cmpLt", 0x21: "cmpLtEqual",
    0x22: "cmpFloatEqual", 0x23: "cmpFloatGt", 0x24: "cmpFloatGtEqual",
    0x25: "cmpFloatLt", 0x26: "cmpFloatLtEqual",
    0x27: "intMod", 0x28: "floatMod", 0x29: "intAbs", 0x2A: "floatAbs",
    0x2D: "branch", 0x2E: "branchIf", 0x2F: "branchIfNot",
    0x30: "opLogNot", 0x31: "opBitAnd", 0x32: "opBitNot", 0x33: "opBitOr",
    0x34: "opBitXor", 0x35: "opBitNor", 0x36: "opLogAnd", 0x37: "opLogOr",
    0x38: "intNeg", 0x39: "floatNeg", 0x3A: "loadParmCnt",
    0x3B: "intAddImm", 0x3C: "intSubImm", 0x3D: "intMulImm", 0x3E: "intDivImm",
    0x3F: "loadStaticI32Imm", 0x40: "loadStaticFloatImm", 0x41: "loadStaticPointerImm",
    0x42: "intAsh", 0x43: "move", 0x44: "loadStaticU32Imm",
    0x45: "loadStaticI8Imm", 0x46: "loadStaticU8Imm",
    0x47: "loadStaticI16Imm", 0x48: "loadStaticU16Imm",
    0x49: "loadStaticI64Imm", 0x4A: "loadStaticU64Imm",
}

ALLIGN = 4
stats_table = {}


def get_pointer_ref(hashid):
    fmt = "=>{}:{}"
    nat = native_table.get(hashid)
    if nat: return fmt.format("NATIVE", nat)
    imp = import_table.get(hashid)
    if imp: return fmt.format("IMPORT", imp)
    loc = local_table.get(hashid)
    if loc: return fmt.format("LOCAL", loc)
    return ""

#
## Printers
#

def print_return(fp, name, inst, code, data):
    return ("{} r{}, r{}".format(name, inst[1], inst[2]), None)

def print_intAdd(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} + r{}".format(inst[1], inst[2], inst[3]))

def print_intSub(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} - r{}".format(inst[1], inst[2], inst[3]))

def print_intMul(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} * r{}".format(inst[1], inst[2], inst[3]))

def print_intDiv(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} / r{}".format(inst[1], inst[2], inst[3]))

def print_floatAdd(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} + r{}".format(inst[1], inst[2], inst[3]))

def print_floatSub(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} - r{}".format(inst[1], inst[2], inst[3]))

def print_floatMul(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} * r{}".format(inst[1], inst[2], inst[3]))

def print_floatDiv(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} / r{}".format(inst[1], inst[2], inst[3]))

def print_move(fp, name, inst, code, data):
    return ("{} r{}, r{}".format(name, inst[1], inst[2]),
            "r{} = r{}".format(inst[1], inst[2]))

def print_call(fp, name, inst, code, data):
    return ("{} r{}, r{}, {}".format(name, inst[1], inst[2], inst[3]), None)

def print_callFf(fp, name, inst, code, data):
    return ("{} r{}, r{}, {}".format(name, inst[1], inst[2], inst[3]), None)

def print_branch(fp, name, inst, code, data):
    off = inst[1] | inst[3] << 8
    return ("{} 0x{:08X}".format(name, code + off * 4),
            "goto 0x{:08X}".format(code + off * 4))

def print_branchIf(fp, name, inst, code, data):
    off = inst[1] | inst[3] << 8
    return ("{} r{}, 0x{:08X}".format(name, inst[2], code + off * 4),
            "if (r{}) goto 0x{:08X}".format(inst[2], code + off * 4))

def print_branchIfNot(fp, name, inst, code, data):
    off = inst[1] | inst[3] << 8
    return ("{} r{}, 0x{:08X}".format(name, inst[2], code + off * 4),
            "if (!r{}) goto 0x{:08X}".format(inst[2], code + off * 4))

def print_lookupPointer(fp, name, inst, code, data):
    s = "{} r{}, data[{}]".format(name, inst[1], inst[2])
    try:
        fp.seek(data + (inst[2] * ALLIGN))
        hashid = read_u32(fp)
    except Exception:
        hashid = 0
    cmt = "r{} = StringId(0x{:08x})".format(inst[1], hashid)
    value = get_pointer_ref(hashid)
    if value:
        cmt += value
    return (s, cmt)

def print_loadStaticU32Imm(fp, name, inst, code, data):
    s = "{} r{}, data[{}]".format(name, inst[1], inst[2])
    offset = data + inst[2] * ALLIGN
    try:
        fp.seek(offset)
        value = read_u32(fp)
    except Exception:
        value = 0
    cmt = "r{} = {} (0x{:08x})".format(inst[1], value, value)
    ref = get_pointer_ref(value)
    if ref:
        cmt += ref
    return (s, cmt)

def print_loadStaticI32Imm(fp, name, inst, code, data):
    s = "{} r{}, data[{}]".format(name, inst[1], inst[2])
    offset = data + inst[2] * ALLIGN
    try:
        fp.seek(offset)
        svalue = read_i32(fp)
        fp.seek(offset)
        value = read_u32(fp)
    except Exception:
        svalue, value = 0, 0
    cmt = "r{} = {} (0x{:8x})".format(inst[1], svalue, value)
    ref = get_pointer_ref(value)
    if ref:
        cmt += ref
    return (s, cmt)

def print_loadStaticFloatImm(fp, name, inst, code, data):
    s = "{} r{}, data[{}]".format(name, inst[1], inst[2])
    offset = data + inst[2] * ALLIGN
    try:
        fp.seek(offset)
        value = read_float(fp)
    except Exception:
        value = 0.0
    return (s, "r{} = {}f offset: 0x{:08X}".format(inst[1], value, offset))

def print_loadStaticPointerImm(fp, name, inst, code, data):
    s = "{} r{}, data[{}]".format(name, inst[1], inst[2])
    offset = data + inst[2] * ALLIGN
    try:
        fp.seek(offset)
        value = read_u32(fp)
        fp.seek(value)
        d = bytearray()
        c = fp.read(1)
        count = 0
        while c != b'\0' and c != b"" and count < 1000:
            d += c
            c = fp.read(1)
            count += 1
        p = d.decode('ascii', errors='replace').replace("\n", "\\n")
    except Exception:
        value, p = 0, ""
    return (s, "r{} = 0x{:08x} (\"{}\")".format(inst[1], value, p))

def print_loadParmCnt(fp, name, inst, code, data):
    return ("{} r{}".format(name, inst[1]), "r{} = argc".format(inst[1]))

def print_loadPointer(fp, name, inst, code, data):
    return ("{} r{}, (r{})".format(name, inst[1], inst[2]),
            "r{} = (ptr)*r{}".format(inst[1], inst[2]))

def print_loadInt(fp, name, inst, code, data):
    return ("{} r{}, (r{})".format(name, inst[1], inst[2]),
            "r{} = (int)*r{}".format(inst[1], inst[2]))

def print_loadFloat(fp, name, inst, code, data):
    return ("{} r{}, (r{})".format(name, inst[1], inst[2]),
            "r{} = (float)*r{}".format(inst[1], inst[2]))

def print_loadImm(fp, name, inst, code, data):
    v = inst[3] << 8 | inst[2]
    return ("{} r{}, 0x{:04x}".format(name, inst[1], v), "r{} = {}".format(inst[1], v))

def print_intAddImm(fp, name, inst, code, data):
    return ("{} r{}, r{}, 0x{:02x}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} + {}".format(inst[1], inst[2], inst[3]))

def print_floatAbs(fp, name, inst, code, data):
    return ("{} r{}, r{}".format(name, inst[1], inst[2]),
            "r{} = Abs(r{})".format(inst[1], inst[2]))

def print_cmpEqual(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} == r{}".format(inst[1], inst[2], inst[3]))

def print_cmpGt(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} > r{}".format(inst[1], inst[2], inst[3]))

def print_cmpLt(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} < r{}".format(inst[1], inst[2], inst[3]))

def print_cmpFloatGt(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} > r{}".format(inst[1], inst[2], inst[3]))

def print_cmpFloatLt(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} < r{}".format(inst[1], inst[2], inst[3]))

def print_opLogNot(fp, name, inst, code, data):
    return ("{} r{}, r{}".format(name, inst[1], inst[2]),
            "r{} = -(r{} == 0)".format(inst[1], inst[2]))

def print_opBitAnd(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} & r{}".format(inst[1], inst[2], inst[3]))

def print_opBitNot(fp, name, inst, code, data):
    return ("{} r{}, r{}".format(name, inst[1], inst[2]),
            "r{} = ~r{}".format(inst[1], inst[2]))

def print_opBitOr(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} | r{}".format(inst[1], inst[2], inst[3]))

def print_opBitXor(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = r{} ^ r{}".format(inst[1], inst[2], inst[3]))

def print_opBitNor(fp, name, inst, code, data):
    return ("{} r{}, r{}, r{}".format(name, inst[1], inst[2], inst[3]),
            "r{} = ~(r{} | r{})".format(inst[1], inst[2], inst[3]))

#
## Loaders
#

def load_dci(fp):
    text = fp.read()
    exports = re.search(r"\(export ([a-zA-Z0-9+-=\?!>\*]*\s?)*", text)
    if exports:
        for exp in exports[0].split()[1:]:
            local_table[StringId(exp)] = exp

def load_sid(fp):
    lineno = 1
    loaded = 0
    skipped = 0
    for line in fp:
        line = line.strip()
        if not line or line.startswith('#'):
            lineno += 1
            continue
        if '#' in line:
            line = line[:line.index('#')].strip()
        entry = line.split(None, 1)
        if len(entry) < 2:
            print(f"ERROR: Invalid entry at line {lineno}: format is <hashid> <string>")
            skipped += 1
            lineno += 1
            continue
        hash_str = entry[0]
        if hash_str.lower().startswith('0x'):
            hash_str = hash_str[2:]
        if not (len(hash_str) == 8 or len(hash_str) == 16):
            print(f"ERROR: Invalid hash id at line {lineno}: must be 8 or 16 hex chars, got {len(hash_str)}")
            skipped += 1
            lineno += 1
            continue
        try:
            hashid = int(hash_str, 16)
        except ValueError:
            print(f"ERROR: Invalid hash id at line {lineno}: {entry[0]}")
            skipped += 1
            lineno += 1
            continue
        native_table[hashid] = entry[1]
        loaded += 1
        lineno += 1
    print(f"Loaded {loaded} SIDs ({skipped} skipped) from {lineno-1} lines")