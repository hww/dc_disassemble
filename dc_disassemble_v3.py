#!/usr/bin/env python3
"""dc_disassemble_v3.py — дизассемблер DC-скриптов (sid32, UC4/T1X).
Поддерживает: script-lambda, function, state-script, blood-effect-map-entry.
"""

import os
import sys
import argparse
import traceback
import struct

from dc_core import (
    StringId, crc32, fnv1a_64,
    script_lambda_id, function_id, boolean_id, int32_id, float_id,
    quat_id, point_id, state_script_id, array_id, inline_array_id,
    darray_id, symbol_array_id, map_id, map_32_id,
    safe_seek, read_u32, read_i32, read_u64, read_i64, read_float, read_u16, read_i16,
    dump, dump_line,
    DcHeader, DcDefinition, DcDescriptor,
    inst_map, ALLIGN, stats_table,
    native_table, local_table, import_table,
    load_sid, load_dci,
)

# ------------------------------------------------------------------
# Константы (sid32)
# ------------------------------------------------------------------
BLOOD_EFFECT_MAP_ENTRY_ID = 0x5D95B08B
NPC_BLOOD_EFFECT_MAP_ID   = 0x2DB90AD2
BODY_PART_ID              = 0xB78A7E53


class DcDisassembler:
    def __init__(self, fp, args):
        self.fp = fp
        self.dcHeader = None
        self.defTable = []
        self.args = args
        self.reloc_slots = set()
        self.reloc_table_size = 0
        self._read_header()
        self._read_reloc_table()
        self._read_fntable()

    # ---------------- header / reloc / fntable ----------------

    def _read_header(self):
        if self.args.verbose:
            print("Read header")
        self.dcHeader = DcHeader(self.fp)
        if self.args.verbose:
            print(f"  magic={self.dcHeader.magic} version={self.dcHeader.version}")
            print(f"  textSize=0x{self.dcHeader.textSize:08X} stringsOffset=0x{self.dcHeader.stringsOffset:08X}")
            print(f"  always1={self.dcHeader.always1} numEntries={self.dcHeader.numEntries} defTableOff=0x{self.dcHeader.defTableOff:08X}")

    def _read_reloc_table(self):
        if self.args.no_reloc:
            return
        try:
            text_size = self.dcHeader.textSize
            self.fp.seek(text_size)
            table_size = read_u32(self.fp)
            if self.args.verbose:
                print(f"  reloc table_size = {table_size} (bytes)")
            bitmap = self.fp.read(table_size)
            if len(bitmap) < table_size:
                if self.args.verbose:
                    print(f"  warning: reloc bitmap truncated ({len(bitmap)}/{table_size})")
                return
            self.reloc_table_size = table_size
            for byte_idx in range(table_size):
                b = bitmap[byte_idx]
                for bit in range(8):
                    if b & (1 << bit):
                        slot_idx = byte_idx * 8 + bit
                        self.reloc_slots.add(slot_idx)
            if self.args.verbose:
                print(f"  loaded {len(self.reloc_slots)} reloc slots")
        except Exception as e:
            if self.args.verbose:
                print(f"  warning: couldn't read reloc table: {e}")

    def _read_fntable(self):
        if self.args.verbose:
            print("Read fntable", self.dcHeader.numEntries)
        self.fp.seek(self.dcHeader.defTableOff)
        for i in range(self.dcHeader.numEntries):
            try:
                definition = DcDefinition(self.fp)
                self.defTable.append(definition)
            except Exception as e:
                print(f"ERROR reading definition {i}: {e}")
                break
        self.defTable.sort(key=lambda d: d.offset)
        if self.args.verbose:
            print(f"  read {len(self.defTable)} definitions")

    # ---------------- helpers ----------------

    def _is_reloc_slot(self, offset):
        return (offset // 4) in self.reloc_slots or (offset // 8) in self.reloc_slots

    def _read_value_at(self, offset):
        try:
            self.fp.seek(offset)
            return read_u32(self.fp)
        except Exception:
            return 0

    def _looks_like_sid(self, value):
        return value in native_table or value in local_table

    def _looks_like_offset(self, value):
        return 0 < value < self.dcHeader.textSize and value % 4 == 0

    def _looks_like_float(self, value):
        try:
            f = struct.unpack('>f', struct.pack('>I', value))[0]
            if f != f:
                return False
            if abs(f) > 1e6:
                return False
            if abs(f) < 1e-10:
                return False
            rounded = round(f * 1e4) / 1e4
            return abs(f - rounded) < 1e-3
        except Exception:
            return False

    def _describe_value(self, v):
        if v in native_table:
            return f"sid: {native_table[v]}"
        if v in local_table:
            return f"sid: {local_table[v]}"
        if self._looks_like_float(v):
            f = struct.unpack('>f', struct.pack('>I', v))[0]
            return f"float: {f:.4f}"
        if 0 < v < self.dcHeader.textSize and v % 4 == 0:
            return f"offset: 0x{v:04X}"
        if v < 0x10000:
            return f"int: {v}"
        return f"int: 0x{v:08X}"

    def _read_cstring(self):
        """Читает нуль-терминированную строку."""
        buf = bytearray()
        while True:
            c = self.fp.read(1)
            if c == b'\0' or c == b'':
                break
            buf += c
        return buf.decode('ascii', errors='replace')

    # ---------------- generic dumps ----------------

    def insert_next_struct_member(self, offset, indent=0):
        value = self._read_value_at(offset)
        prefix = "  " * indent
        if self._looks_like_sid(value):
            name = native_table.get(value) or local_table.get(value)
            return 4, f"{prefix}[0x{offset:04X}] sid: {name}"
        if self._is_reloc_slot(offset):
            return 4, f"{prefix}[0x{offset:04X}] ptr = 0x{value:08X}"
        if self._looks_like_float(value):
            f = struct.unpack('>f', struct.pack('>I', value))[0]
            return 4, f"{prefix}[0x{offset:04X}] float: {f:.4f}"
        if self._looks_like_offset(value):
            return 4, f"{prefix}[0x{offset:04X}] offset: 0x{value:04X}"
        if value < 0x10000:
            return 4, f"{prefix}[0x{offset:04X}] int: {value}"
        return 4, f"{prefix}[0x{offset:04X}] int: 0x{value:08X}"

    def dump_struct(self, offset, indent=0, max_depth=2, max_size=128):
        if max_depth <= 0:
            return
        prefix = "  " * indent
        print(f"{prefix}struct at 0x{offset:04X} {{")
        end = min(offset + max_size, self.dcHeader.textSize)
        cur = offset
        while cur < end:
            size, desc = self.insert_next_struct_member(cur, indent + 1)
            print(desc)
            value = self._read_value_at(cur)
            if (self._looks_like_offset(value)
                    and not self._looks_like_sid(value)
                    and not self._is_reloc_slot(cur)
                    and max_depth > 1):
                try:
                    self.fp.seek(value)
                    sub_value = read_u32(self.fp)
                    sub_desc = self._describe_value(sub_value)
                    print(f"{prefix}  -> 0x{value:04X}: {sub_desc}")
                except Exception:
                    pass
            cur += size
        print(f"{prefix}}}")

    def dump_data_at(self, offset, indent=0, max_size=256):
        """Дамп данных blood-effect-map (24-байтные записи)."""
        prefix = "  " * indent
        print(f"{prefix}data at 0x{offset:04X} {{")
        end = min(offset + max_size, self.dcHeader.textSize)
        cur = offset
        idx = 0
        while cur < end:
            try:
                self.fp.seek(cur)
                v0 = read_u32(self.fp)
                v1 = read_u32(self.fp)
                v2 = read_u32(self.fp)
                v3 = read_u32(self.fp)
                v4 = read_u32(self.fp)
                v5 = read_u32(self.fp)
            except Exception:
                break
            s0 = self._describe_value(v0)
            s1 = self._describe_value(v1)
            s2 = self._describe_value(v2)
            s3 = self._describe_value(v3)
            s4 = self._describe_value(v4)
            s5 = self._describe_value(v5)
            print(f"{prefix}  [{idx:03d}] 0x{cur:04X}: "
                  f"count={v0} ({s0}) | off=0x{v1:04X} ({s1}) | sid=0x{v2:08X} ({s2})")
            print(f"{prefix}         "
                  f"value={v3} ({s3}) | off2=0x{v4:04X} ({s4}) | sid2=0x{v5:08X} ({s5})")
            cur += 24
            idx += 1
        print(f"{prefix}}}")

    # ---------------- state-script ----------------

    def dump_state_script(self, offset, indent=0):
        prefix = "  " * indent
        self.fp.seek(offset)

        # StateScript (0x30 = 48 байт в sid32)
        m_stateScriptId    = read_u32(self.fp)
        m_pSsDeclList      = read_u32(self.fp)
        m_initialStateId   = read_u32(self.fp)
        m_pSsOptions       = read_u32(self.fp)
        m_always0_1        = read_u32(self.fp)
        m_always0_2        = read_u32(self.fp)
        m_pSsStateTable    = read_u32(self.fp)
        m_stateCount_line  = read_u32(self.fp)
        m_pDebugFileName   = read_u32(self.fp)
        m_pErrorName       = read_u32(self.fp)
        m_padding1         = read_u32(self.fp)
        m_unknown          = read_u32(self.fp)

        m_stateCount = (m_stateCount_line >> 16) & 0xFFFF
        m_line       = m_stateCount_line & 0xFFFF

        print(f"{prefix}StateScript {{")
        print(f"{prefix}  m_stateScriptId  = 0x{m_stateScriptId:08X} ({native_table.get(m_stateScriptId, '?')})")
        print(f"{prefix}  m_pSsDeclList    = 0x{m_pSsDeclList:04X}")
        print(f"{prefix}  m_initialStateId = 0x{m_initialStateId:08X} ({native_table.get(m_initialStateId, '?')})")
        print(f"{prefix}  m_pSsOptions     = 0x{m_pSsOptions:04X}")
        print(f"{prefix}  m_pSsStateTable  = 0x{m_pSsStateTable:04X}")
        print(f"{prefix}  m_stateCount     = {m_stateCount}")
        print(f"{prefix}  m_line           = {m_line}")
        print(f"{prefix}  m_pDebugFileName = 0x{m_pDebugFileName:04X}")
        if m_pDebugFileName:
            self.fp.seek(m_pDebugFileName)
            s = self._read_cstring()
            print(f"{prefix}    \"{s}\"")
        print(f"{prefix}  m_pErrorName     = 0x{m_pErrorName:08X}")
        print(f"{prefix}}}")

        if m_pSsDeclList:
            self.dump_ss_declaration_list(m_pSsDeclList, indent + 1)

        if m_pSsOptions:
            self.dump_ss_options(m_pSsOptions, indent + 1)

        if m_pSsStateTable:
            self.dump_ss_states(m_pSsStateTable, m_stateCount, indent + 1)

    def dump_ss_declaration_list(self, offset, indent=0):
        prefix = "  " * indent
        self.fp.seek(offset)
        m_totalDeclarationSize = read_u32(self.fp)
        m_numDeclarations      = read_u32(self.fp)
        m_pDeclarations        = read_u32(self.fp)

        print(f"{prefix}SsDeclarationList {{")
        print(f"{prefix}  m_totalDeclarationSize = {m_totalDeclarationSize}")
        print(f"{prefix}  m_numDeclarations      = {m_numDeclarations}")
        print(f"{prefix}  m_pDeclarations        = 0x{m_pDeclarations:04X}")
        print(f"{prefix}}}")

        if m_pDeclarations:
            self.dump_ss_declarations(m_pDeclarations, m_numDeclarations, indent + 1)

    def dump_ss_declarations(self, offset, count, indent=0):
        prefix = "  " * indent
        print(f"{prefix}SsDeclaration[{count}] {{")
        for i in range(count):
            off = offset + i * 0x10
            self.fp.seek(off)
            m_declId        = read_u32(self.fp)
            m_declTypeId    = read_u32(self.fp)
            m_varSize_isVar = read_u32(self.fp)
            m_pDeclValue    = read_u32(self.fp)

            declId_name   = native_table.get(m_declId, f"0x{m_declId:08X}")
            declType_name = native_table.get(m_declTypeId, f"0x{m_declTypeId:08X}")

            print(f"{prefix}  [{i}] declId=0x{m_declId:08X} ({declId_name}) "
                  f"typeId=0x{m_declTypeId:08X} ({declType_name}) "
                  f"pDeclValue=0x{m_pDeclValue:04X}")
        print(f"{prefix}}}")

    def dump_ss_options(self, offset, indent=0):
        prefix = "  " * indent
        self.fp.seek(offset)
        m_optionString   = read_u32(self.fp)
        m_unknownFlags   = read_u32(self.fp)
        m_always0_1      = read_u32(self.fp)
        m_pSymbolArray   = read_u32(self.fp)
        m_symbolArray2   = read_u32(self.fp)
        m_symbolArray3   = read_u32(self.fp)
        m_symbolArray4   = read_u32(self.fp)
        m_always5        = read_u32(self.fp)
        m_mostly0        = read_u32(self.fp)
        m_mostly0Rarely1 = read_u32(self.fp)

        print(f"{prefix}SsOptions {{")
        print(f"{prefix}  m_optionString   = 0x{m_optionString:04X}")
        if m_optionString:
            # Читаем только до m_pDebugFileName (или до 4 строк)
            max_end = self.dcHeader.textSize
            if hasattr(self, 'current_debug_filename') and self.current_debug_filename:
                max_end = min(max_end, self.current_debug_filename)

            self.fp.seek(m_optionString)
            all_opts = []
            cur = m_optionString
            while cur < max_end and len(all_opts) < 8:
                self.fp.seek(cur)
                s = self._read_cstring()
                if not s:
                    break
                all_opts.append(s)
                cur = self.fp.tell()
            for opt in all_opts:
                print(f"{prefix}    \"{opt}\"")
        print(f"{prefix}  m_unknownFlags   = 0x{m_unknownFlags:08X}")
        print(f"{prefix}  m_pSymbolArray   = 0x{m_pSymbolArray:04X}")
        print(f"{prefix}  m_symbolArray2   = 0x{m_symbolArray2:04X}")
        print(f"{prefix}  m_symbolArray3   = 0x{m_symbolArray3:04X}")
        print(f"{prefix}  m_symbolArray4   = 0x{m_symbolArray4:04X}")
        print(f"{prefix}  m_always5        = {m_always5}")
        print(f"{prefix}}}")

    def dump_ss_states(self, offset, count, indent=0):
        prefix = "  " * indent
        print(f"{prefix}SsState[{count}] {{")
        for i in range(count):
            off = offset + i * 0x0C
            self.fp.seek(off)
            m_stateId       = read_u32(self.fp)
            m_numSsOnBlocks = read_u32(self.fp)
            m_pSsOnBlocks   = read_u32(self.fp)

            state_name = native_table.get(m_stateId, f"0x{m_stateId:08X}")
            print(f"{prefix}  [{i}] stateId=0x{m_stateId:08X} ({state_name}) "
                  f"numSsOnBlocks={m_numSsOnBlocks} pSsOnBlocks=0x{m_pSsOnBlocks:04X}")

            if m_pSsOnBlocks and m_numSsOnBlocks > 0:
                self.dump_ss_on_blocks(m_pSsOnBlocks, m_numSsOnBlocks, indent + 2)
        print(f"{prefix}}}")

    def dump_ss_on_blocks(self, offset, count, indent=0):
        prefix = "  " * indent
        print(f"{prefix}SsOnBlock[{count}] {{")
        for i in range(count):
            off = offset + i * 0x20
            self.fp.seek(off)
            m_unknown1          = read_u32(self.fp)
            m_blockEventId      = read_u32(self.fp)
            m_blockType         = read_u32(self.fp)
            m_totalLambda_count = read_u32(self.fp)
            m_aTracks           = read_u32(self.fp)
            m_name              = read_u32(self.fp)
            m_always0_1         = read_u32(self.fp)
            m_always0_2         = read_u32(self.fp)

            total_lambdas = (m_totalLambda_count >> 16) & 0xFFFF
            num_tracks    = m_totalLambda_count & 0xFFFF

            event_name = native_table.get(m_blockEventId, f"0x{m_blockEventId:08X}") if m_blockEventId else "None"

            # Определяем тип по имени строки (надёжнее, чем m_blockType)
            block_type_name = f"?{m_blockType}"
            if m_name:
                self.fp.seek(m_name)
                name_str = self._read_cstring()
                if "(on (start))" in name_str:
                    block_type_name = "Start"
                elif "(on (end))" in name_str:
                    block_type_name = "End"
                elif "(on (event))" in name_str:
                    block_type_name = "Event"
                elif "(on (update))" in name_str:
                    block_type_name = "Update"
                elif "(on (virtual))" in name_str:
                    block_type_name = "Virtual"

            print(f"{prefix}  [{i}] eventId=0x{m_blockEventId:08X} ({event_name}) "
                  f"type={block_type_name} totalLambdas={total_lambdas} numTracks={num_tracks} "
                  f"aTracks=0x{m_aTracks:04X} name=0x{m_name:04X}")
            if m_name:
                self.fp.seek(m_name)
                s = self._read_cstring()
                print(f"{prefix}      name=\"{s}\"")

            if m_aTracks and num_tracks > 0:
                self.dump_ss_tracks(m_aTracks, num_tracks, indent + 2)
        print(f"{prefix}}}")

    # ---------------- SsTrack / SsLambda / ScriptLambda ----------------

    def dump_ss_tracks(self, offset, count, indent=0):
        """SsTrack[] — 0x10 = 16 байт на элемент (sid32)."""
        prefix = "  " * indent
        if count == 0:
            return
        print(f"{prefix}SsTrack[{count}] {{")
        for i in range(count):
            off = offset + i * 0x10
            self.fp.seek(off)
            m_trackId          = read_u32(self.fp)
            m_trackIdx_count   = read_u32(self.fp)
            m_pSsLambda        = read_u32(self.fp)
            m_type             = read_u32(self.fp)

            m_trackIdx         = (m_trackIdx_count >> 16) & 0xFFFF
            m_totalLambdaCount = m_trackIdx_count & 0xFFFF

            track_name = native_table.get(m_trackId, f"0x{m_trackId:08X}")
            type_name  = native_table.get(m_type, f"0x{m_type:08X}")

            print(f"{prefix}  [{i}] @0x{off:04X} trackId=0x{m_trackId:08X} ({track_name}) "
                f"trackIdx={m_trackIdx} totalLambdas={m_totalLambdaCount} "
                f"pSsLambda=0x{m_pSsLambda:04X} type=0x{m_type:08X} ({type_name})")

            if m_pSsLambda and m_pSsLambda < self.dcHeader.textSize and m_totalLambdaCount > 0:
                self.dump_ss_lambdas(m_pSsLambda, m_totalLambdaCount, indent + 2)
        print(f"{prefix}}}")

    def dump_ss_lambdas(self, offset, count, indent=0):
        """SsLambda[] — 0x08 = 8 байт на элемент (sid32)."""
        prefix = "  " * indent
        print(f"{prefix}SsLambda[{count}] {{")
        for i in range(count):
            off = offset + i * 0x08
            self.fp.seek(off)
            m_pScriptLambda     = read_u32(self.fp)
            m_someSortOfCounter = read_u32(self.fp)

            print(f"{prefix}  [{i}] pScriptLambda=0x{m_pScriptLambda:04X} "
                  f"counter={m_someSortOfCounter}")

            if m_pScriptLambda and m_pScriptLambda < self.dcHeader.textSize:
                try:
                    self.dump_script_lambda(m_pScriptLambda, indent + 2)
                except Exception as e:
                    print(f"{prefix}    ERROR reading ScriptLambda: {e}")
        print(f"{prefix}}}")

    def dump_script_lambda(self, offset, indent=0):
        prefix = "  " * indent
        self.fp.seek(offset)

        m_pInstruction = read_u32(self.fp)
        m_pSymbols     = read_u32(self.fp)
        m_typeId       = read_u32(self.fp)
        m_sum          = read_u32(self.fp)
        m_funcName     = read_u32(self.fp)
        m_type         = read_u32(self.fp)

        type_name = native_table.get(m_type, f"0x{m_type:08X}")
        num_instr = (m_pSymbols - m_pInstruction) // 4 if m_pSymbols > m_pInstruction else 0

        print(f"{prefix}ScriptLambda @0x{offset:04X} {{")
        print(f"{prefix}  m_pInstruction = 0x{m_pInstruction:04X}")
        print(f"{prefix}  m_pSymbols     = 0x{m_pSymbols:04X}")
        print(f"{prefix}  m_typeId       = 0x{m_typeId:08X} ({native_table.get(m_typeId, '?')})")
        print(f"{prefix}  m_type         = 0x{m_type:08X} ({type_name})")
        print(f"{prefix}}}")

        if m_pSymbols and m_pSymbols < self.dcHeader.textSize:
            self.dump_symbol_table(m_pSymbols, 16, indent + 1)

        if m_pInstruction and num_instr > 0:
            print(f"{prefix}  --- bytecode ({num_instr} instructions) ---")
            self._disassemble_lambda_at(m_pInstruction, num_instr, indent + 2)

    def _disassemble_lambda_at(self, offset, count, indent=0):
        """Дизассемблирует байткод лямбды."""
        prefix = "  " * indent
        for i in range(count):
            instOff = offset + i * 4
            try:
                self.fp.seek(instOff)
                inst = self.fp.read(4)
            except Exception:
                break
            if len(inst) < 4:
                break
            self._print_inst(instOff, inst, offset, offset + count * 4)
            if inst[0] == 0:
                break

    def dump_symbol_table(self, offset, count, indent=0):
        """Symbol table лямбды. Читает до первого не-SID или opcode."""
        prefix = "  " * indent
        symbols = []
        cur = offset
        max_read = min(count * 4 + 32, 256)  # не больше 256 байт
        end = min(offset + max_read, self.dcHeader.textSize)

        while cur + 4 <= end:
            self.fp.seek(cur)
            value = read_u32(self.fp)

            # SID?
            if value in native_table:
                symbols.append((cur, 'sid', value, native_table[value]))
                cur += 4
                continue
            elif value in local_table:
                symbols.append((cur, 'sid', value, local_table[value]))
                cur += 4
                continue
            # Строка?
            elif 0 < value < self.dcHeader.textSize and value % 4 == 0:
                try:
                    self.fp.seek(value)
                    s = self._read_cstring()
                    if s and len(s) < 128 and all(32 <= ord(c) < 127 for c in s):
                        symbols.append((cur, 'string', value, s))
                        cur += 4
                        continue
                except Exception:
                    pass
            # Всё остальное — стоп
            break

        if not symbols:
            return

        print(f"{prefix}SymbolTable[{len(symbols)}] {{")
        for i, (off, kind, value, name) in enumerate(symbols):
            if kind == 'sid':
                print(f"{prefix}  [{i}] 0x{value:08X} sid: {name}")
            elif kind == 'string':
                print(f"{prefix}  [{i}] 0x{value:08X} string: \"{name}\"")
        print(f"{prefix}}}")

    # ---------------- main disassemble ----------------

    def disassemble(self):
        found_anything = False
        file_shown = False
        dumped_structs = 0

        for definition in self.defTable:
            try:
                funcName = native_table.get(definition.nameId) or local_table.get(definition.nameId)
                typeName = native_table.get(definition.typeId) or local_table.get(definition.typeId)
                if not funcName:
                    funcName = "<name {:X}>".format(definition.nameId)
                if not typeName:
                    typeName = "<type {:X}>".format(definition.typeId)

                # Фильтры
                if self.args.only_script_lambda:
                    if definition.typeId not in (script_lambda_id, function_id):
                        continue
                if self.args.type_filter and definition.typeId != self.args.type_filter:
                    continue
                if self.args.name_filter:
                    if self.args.name_filter.startswith('0x'):
                        try:
                            name_filter_id = int(self.args.name_filter, 16)
                            if definition.nameId != name_filter_id:
                                continue
                        except ValueError:
                            pass
                    else:
                        if funcName != self.args.name_filter and not funcName.startswith(self.args.name_filter):
                            continue

                if self.args.dump_structs and self.args.max_structs > 0:
                    if dumped_structs >= self.args.max_structs:
                        continue

                if not file_shown:
                    print(f"\n=== Файл: {self.args.input_file} ===")
                    self.print_header_info()
                    self.print_definitions_summary()
                    file_shown = True
                    found_anything = True

                print()
                print("Name:", funcName, " NameId: 0x{:08X}".format(definition.nameId))
                print("Type:", typeName, " TypeId: 0x{:08X}".format(definition.typeId))
                print("Defn: 0x{:08X}: Body at: 0x{:08X}:".format(definition.defOffset, definition.offset))

                # script-lambda / function
                if definition.typeId in (script_lambda_id, function_id):
                    try:
                        self.fp.seek(definition.offset)
                        descriptor = DcDescriptor(self.fp)
                        if not funcName:
                            funcName = "func_{:X}".format(descriptor.start)
                        print("Code: 0x{:08X}: Data: 0x{:08X}:".format(descriptor.start, descriptor.end))
                        self._disassemble_lambda(descriptor, funcName)
                        dump(self.fp, descriptor.end, descriptor.data_size)
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        traceback.print_exc()

                # state-script
                elif definition.typeId == state_script_id:
                    try:
                        self.dump_state_script(definition.offset, indent=1)
                        dumped_structs += 1
                    except Exception as e:
                        print(f"  ERROR: {e}")
                        traceback.print_exc()

                # blood-effect-map-entry
                elif definition.typeId == BLOOD_EFFECT_MAP_ENTRY_ID:
                    try:
                        self.fp.seek(definition.offset)
                        body_nameId = read_u32(self.fp)
                        body_offset = read_u32(self.fp)
                        body_typeId = read_u32(self.fp)
                        body_name = native_table.get(body_nameId, f"0x{body_nameId:08X}")
                        body_type = native_table.get(body_typeId, f"0x{body_typeId:08X}")
                        print(f"  body: nameId=0x{body_nameId:08X} ({body_name}) "
                              f"data_offset=0x{body_offset:04X} typeId=0x{body_typeId:08X} ({body_type})")
                        if self.args.dump_structs:
                            self.dump_data_at(body_offset, indent=1)
                            dumped_structs += 1
                    except Exception as e:
                        print(f"  ERROR: {e}")

                # примитивы
                elif definition.typeId == boolean_id:
                    try:
                        self.fp.seek(definition.offset)
                        x = read_u32(self.fp)
                        print("boolean: 0x{:08X}".format(x))
                    except Exception as e:
                        print(f"  ERROR: {e}")

                elif definition.typeId == int32_id:
                    try:
                        self.fp.seek(definition.offset)
                        x = read_u32(self.fp)
                        print("int32: 0x{:08X}".format(x))
                    except Exception as e:
                        print(f"  ERROR: {e}")

                elif definition.typeId == float_id:
                    try:
                        self.fp.seek(definition.offset)
                        x = read_float(self.fp)
                        print("float:", x)
                    except Exception as e:
                        print(f"  ERROR: {e}")

                elif definition.typeId == quat_id:
                    try:
                        self.fp.seek(definition.offset)
                        x = read_float(self.fp); y = read_float(self.fp)
                        z = read_float(self.fp); w = read_float(self.fp)
                        print("quat:", x, y, z, w)
                    except Exception as e:
                        print(f"  ERROR: {e}")

                elif definition.typeId == point_id:
                    try:
                        self.fp.seek(definition.offset)
                        x = read_float(self.fp); y = read_float(self.fp); z = read_float(self.fp)
                        print("point:", x, y, z)
                    except Exception as e:
                        print(f"  ERROR: {e}")

                # array / inline-array / darray / symbol-array (TODO)
                elif definition.typeId in (array_id, inline_array_id, darray_id, symbol_array_id):
                    print(f"  {typeName}: (TODO: parser)")
                    if self.args.dump_structs:
                        self.dump_struct(definition.offset, indent=1)
                        dumped_structs += 1

                # map / map-32 (TODO)
                elif definition.typeId in (map_id, map_32_id):
                    print(f"  {typeName}: (TODO: parser)")
                    if self.args.dump_structs:
                        self.dump_struct(definition.offset, indent=1)
                        dumped_structs += 1

                # generic
                elif self.args.dump_structs:
                    try:
                        self.dump_struct(definition.offset)
                        dumped_structs += 1
                    except Exception as e:
                        print(f"  ERROR: {e}")

                else:
                    if not self.args.only_script_lambda:
                        dump(self.fp, definition.offset, 32)

            except Exception as e:
                print(f"\n!!! ERROR on definition at 0x{definition.defOffset:08X}: {e}")
                traceback.print_exc()
                continue

        if not found_anything and self.args.verbose:
            print(f"Файл: {self.args.input_file} - ничего не найдено по заданным фильтрам")

    def _disassemble_lambda(self, descriptor, funcName):
        max_instructions = 100000
        instruction_count = 0
        for instOff in range(descriptor.start, descriptor.end, 4):
            if instruction_count >= max_instructions:
                print(f"; WARNING: reached max instructions ({max_instructions})")
                break
            try:
                self.fp.seek(instOff)
                inst = self.fp.read(4)
            except Exception:
                break
            if len(inst) < 4:
                break
            self._print_inst(instOff, inst, descriptor.start, descriptor.end)
            instruction_count += 1
            if inst[0] == 0:
                break

    def _print_inst(self, offset, inst, code, data):
        stats_table[inst[0]] = stats_table.get(inst[0], 0) + 1
        print("0x{:08X}: ".format(offset) + ("{:02X} " * 4).format(inst[0], inst[1], inst[2], inst[3]), end="")
        name = inst_map.get(inst[0])
        if not name:
            print()
            return
        printer = globals().get("print_" + name)
        if not printer:
            print(name + " r{}, r{}, r{}".format(inst[1], inst[2], inst[3]))
            return
        l = printer(self.fp, name, inst, code, data)
        print(l[0].ljust(40), end="")
        if l[1]:
            print("# {}".format(l[1]))
        else:
            print()

    # ---------------- refs ----------------

    def find_function_references(self, target_func_id):
        references = []
        for definition in self.defTable:
            if definition.typeId in (script_lambda_id, function_id):
                try:
                    self.fp.seek(definition.offset)
                    descriptor = DcDescriptor(self.fp)
                    func_name = native_table.get(definition.nameId, f"func_{definition.defOffset:X}")
                    data_start = descriptor.end
                    data_refs = []
                    for i in range(0, 1024, 4):
                        try:
                            self.fp.seek(data_start + i)
                            value = read_u32(self.fp)
                            if value == target_func_id:
                                data_refs.append({'offset': i, 'data_index': i // 4})
                        except Exception:
                            break
                    if data_refs:
                        references.append({
                            'function': func_name,
                            'def_offset': definition.defOffset,
                            'code_start': descriptor.start,
                            'data_start': data_start,
                            'references': data_refs
                        })
                except Exception:
                    continue
        return references

    def print_function_references(self, references, func_name):
        if not references:
            print(f"Ссылки на '{func_name}' не найдены")
            return
        print(f"\n=== НАЙДЕНО {len(references)} ССЫЛОК НА '{func_name.upper()}' ===")
        for ref in references:
            print(f"\nФункция: {ref['function']}")
            print(f"  Defn: 0x{ref['def_offset']:08X}")
            print(f"  Code: 0x{ref['code_start']:08X}")
            for data_ref in ref['references']:
                print(f"    data[{data_ref['data_index']}] @ 0x{ref['data_start'] + data_ref['offset']:08X}")

    # ---------------- header info ----------------

    def print_header_info(self):
        print("\n=== HEADER INFORMATION ===")
        print(f"Magic: {self.dcHeader.magic.decode('ascii', errors='replace')}")
        print(f"Version: 0x{self.dcHeader.version:08X}")
        print(f"Text size: 0x{self.dcHeader.textSize:08X}")
        print(f"Strings offset: 0x{self.dcHeader.stringsOffset:08X}")
        print(f"Always1: 0x{self.dcHeader.always1:08X}")
        print(f"Definition count: {self.dcHeader.numEntries}")
        print(f"Definition table offset: 0x{self.dcHeader.defTableOff:08X}")
        print(f"Reloc table size: {self.reloc_table_size} bytes ({len(self.reloc_slots)} slots)")
        print()

    def print_definitions_summary(self):
        print("=== DEFINITIONS SUMMARY ===")
        print(f"Total definitions: {len(self.defTable)}")
        print("\n{:<4} {:<8} {:<20} {:<12} {:<12} {:<12}".format(
            "#", "Offset", "Name", "NameId", "Type", "TypeId"))
        print("-" * 85)

        type_counts = {}
        for i, definition in enumerate(self.defTable):
            funcName = native_table.get(definition.nameId) or local_table.get(definition.nameId)
            typeName = native_table.get(definition.typeId) or local_table.get(definition.typeId)

            if not funcName:
                funcName = "UNKNOWN"
            if not typeName:
                typeName = f"<type 0x{definition.typeId:08X}>"
                type_counts[definition.typeId] = type_counts.get(definition.typeId, 0) + 1

            print("{:<4} 0x{:<6X} {:<20} 0x{:<8X} {:<12} 0x{:<8X}".format(
                i,
                definition.defOffset,
                funcName[:18] + ".." if len(funcName) > 20 else funcName,
                definition.nameId,
                typeName[:10] + ".." if len(typeName) > 12 else typeName,
                definition.typeId))
        print()

        if type_counts:
            print("Unknown types summary:")
            for type_id, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
                print(f"  TypeId 0x{type_id:08X}: {count} occurrences")


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------

def parse_arguments():
    parser = argparse.ArgumentParser(description='DC Script Disassembler')
    parser.add_argument('input_file', help='Input script file (.bin)')
    parser.add_argument('--only-script-lambda', '-l', action='store_true',
                        help='Show only script-lambda and function types')
    parser.add_argument('--type-filter', '-t', type=str,
                        help='Filter by specific type (hex string)')
    parser.add_argument('--name-filter', '-n', type=str,
                        help='Filter by specific name')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Enable verbose output')
    parser.add_argument('--find-refs', type=str,
                        help='Найти ссылки на функцию (по имени)')
    parser.add_argument('--dump-structs', action='store_true',
                        help='Рекурсивно дампить тела структур с эвристиками')
    parser.add_argument('--max-structs', type=int, default=3,
                        help='Макс. число структур для дампа (0 = без лимита)')
    parser.add_argument('--no-reloc', action='store_true',
                        help='Не читать reloc-таблицу (для отладки)')
    return parser.parse_args()


def main():
    args = parse_arguments()

    if not os.path.exists(args.input_file):
        print(f"Error: File {args.input_file} not found")
        sys.exit(1)

    if args.type_filter:
        try:
            args.type_filter = int(args.type_filter, 16)
        except ValueError:
            print(f"Error: Invalid type filter '{args.type_filter}', must be a hex string")
            sys.exit(1)

    for i in range(0, 0x4A):
        stats_table[i] = 0

    dci = args.input_file.split(".")[0] + ".dci"
    if os.path.exists(dci):
        if args.verbose:
            print("Load DCI files...")
        with open(dci, 'r') as fp:
            load_dci(fp)

    fsids = os.path.dirname(os.path.abspath(__file__)) + "/sids.txt"
    if os.path.exists(fsids):
        if args.verbose:
            print("Load SIDS file...")
        with open(fsids, 'r') as fp:
            load_sid(fp)

    try:
        with open(args.input_file, 'rb') as fp:
            if args.verbose:
                print("Load BIN file...")
            disassembler = DcDisassembler(fp, args)

            if args.find_refs:
                target_id = StringId(args.find_refs)
                references = disassembler.find_function_references(target_id)
                disassembler.print_function_references(references, args.find_refs)
            else:
                if args.verbose:
                    print("Disassemble...")
                disassembler.disassemble()
    except Exception as e:
        print(f"\n!!! FATAL ERROR on {args.input_file}: {e}")
        traceback.print_exc()
        sys.exit(1)

    if args.verbose:
        print("Stats, ", args.input_file, ",", end="")
        for i in range(0, 0x4A):
            print(stats_table[i], ",", end="")
        print()


if __name__ == "__main__":
    main()