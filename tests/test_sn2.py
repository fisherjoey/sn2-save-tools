"""Tests built from synthetic byte streams. No real save files or Oodle library needed."""
import os
import struct
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import ueprops  # noqa: E402
import sn2blob  # noqa: E402
import sn2goals  # noqa: E402
import sn2patch  # noqa: E402
from sn2patch import fstr, tag, NONE, goal_entry, PLAYER, WORLD  # noqa: E402

BYTES_ARRAY = ('ArrayProperty', [('ByteProperty', [])])


def i32(v):
    return struct.pack('<i', v)


def container(guid, goal_names):
    """One SaveData map entry: guid + {Data: bytes holding a StoryGoals struct}."""
    entries = b''.join(goal_entry(n) for n in goal_names)
    entries_payload = i32(len(goal_names)) + entries
    sg_payload = tag('Entries', ('ArrayProperty', [('StructProperty', [])]), len(entries_payload)) + entries_payload + NONE
    inner = b'\x00' + tag('StoryGoals', ('StructProperty', [('UWEStoryGoalData', [])]), len(sg_payload)) + sg_payload + NONE
    data_payload = i32(len(inner)) + inner
    return guid + tag('Data', BYTES_ARRAY, len(data_payload)) + data_payload + NONE


def game_stream(player_goals, world_goals):
    """A decompressed GameData stream: int32 len, u8 0, tagged properties."""
    items = [container(PLAYER, player_goals), container(WORLD, world_goals)]
    sd_payload = i32(0) + i32(len(items)) + b''.join(items)
    body = b'\x00' + tag('SaveData', ('MapProperty', [('StructProperty', []), ('StructProperty', [])]), len(sd_payload)) + sd_payload + NONE
    return i32(len(body)) + body


def stored_block(raw, comp=0):
    """A single SerializeCompressed v2 block with the given format byte."""
    return (sn2blob.TAG + struct.pack('<q', 131072) + bytes([comp])
            + struct.pack('<qq', len(raw), len(raw)) + struct.pack('<qq', len(raw), len(raw)) + raw)


def goal_names(stream, guid):
    L = sn2goals.locate(stream, guid)
    names = []
    for s, e in L['ents']:
        sg, _ = sn2goals.props(stream, s, e)
        inner, _ = sn2goals.props(stream, sg[0]['payload'], sg[0]['next'])
        pan = [x for x in inner if x['name'] == 'PrimaryAssetName'][0]
        names.append(ueprops.rstr(stream, pan['payload'])[0])
    return names


class StringAndTypeTests(unittest.TestCase):
    def test_rstr_ascii_empty_and_utf16(self):
        self.assertEqual(ueprops.rstr(fstr('Hello'), 0), ('Hello', 10))
        self.assertEqual(ueprops.rstr(i32(0), 0), ('', 4))
        wide = 'Hé'.encode('utf-16-le') + b'\0\0'
        self.assertEqual(ueprops.rstr(i32(-3) + wide, 0), ('Hé', 10))

    def test_type_tree_round_trip(self):
        t = ('MapProperty', [('StructProperty', [('Guid', [])]), ('IntProperty', [])])
        raw = tag('X', t, 0)
        _, p = ueprops.rstr(raw, 0)
        parsed, _ = ueprops.rtype(raw, p)
        self.assertEqual(parsed, t)
        self.assertEqual(ueprops.tstr(parsed), 'MapProperty<StructProperty<Guid>,IntProperty>')

    def test_props_reads_sizes_and_stops_at_none(self):
        raw = tag('A', ('IntProperty', []), 4) + i32(7) + tag('B', ('NameProperty', []), len(fstr('hi'))) + fstr('hi') + NONE
        out, end = sn2goals.props(raw, 0, len(raw))
        self.assertEqual([x['name'] for x in out], ['A', 'B'])
        self.assertEqual(out[0]['type'], 'IntProperty')
        self.assertEqual(end, len(raw))


class BlobTests(unittest.TestCase):
    def test_find_and_decode_uncompressed_blocks(self):
        a, b = b'first block', b'second'
        data = b'GSWU' + b'\x00' * 12 + stored_block(a) + stored_block(b)
        blobs = sn2blob.find_blobs(data)
        self.assertEqual(len(blobs), 2)
        self.assertEqual([sn2blob.decompress_blob(data, x) for x in blobs], [a, b])
        start = blobs[0]['tag_off']
        self.assertEqual(sn2patch.decode_buffer(data, start, len(data)), a + b)


class GoalTests(unittest.TestCase):
    def test_locate_lists_existing_goals(self):
        s = game_stream(['DA_A', 'DA_B'], ['DA_W'])
        self.assertEqual(goal_names(s, PLAYER), ['DA_A', 'DA_B'])
        self.assertEqual(goal_names(s, WORLD), ['DA_W'])
        self.assertIsNone(sn2goals.locate(s, b'\x11' * 16))

    def test_add_goals_updates_counts_and_sizes(self):
        s = game_stream(['DA_A'], ['DA_W'])
        new, added = sn2patch.add_goals(s, PLAYER, ['DA_New1', 'DA_New2'])
        self.assertEqual(added, ['DA_New1', 'DA_New2'])
        self.assertEqual(struct.unpack_from('<i', new, 0)[0], len(new) - 4)
        self.assertEqual(goal_names(new, PLAYER), ['DA_A', 'DA_New1', 'DA_New2'])
        self.assertEqual(goal_names(new, WORLD), ['DA_W'])
        # The top-level property list must still parse to the end of the stream.
        _, end = sn2goals.props(new, 5, len(new))
        self.assertEqual(end, len(new))

    def test_add_goals_skips_duplicates(self):
        s = game_stream(['DA_A'], [])
        new, added = sn2patch.add_goals(s, PLAYER, ['DA_A'])
        self.assertEqual(added, [])
        self.assertEqual(new, s)


class PatchFileTests(unittest.TestCase):
    def test_patch_file_end_to_end_with_stub_compression(self):
        def save_blob(stream):
            enc = stored_block(stream, comp=2)
            data_payload = i32(len(enc)) + enc
            gd_payload = tag('Data', BYTES_ARRAY, len(data_payload)) + data_payload + NONE
            return tag('GameData', ('StructProperty', [('UWESaveBuffer', [])]), len(gd_payload)) + gd_payload + NONE

        blobs = [save_blob(game_stream(['DA_A'], ['DA_W'])), save_blob(game_stream([], []))]
        ssg_payload = i32(len(blobs)) + b''.join(blobs)
        ci = i32(1)
        body = (tag('ContainerInfo', ('IntProperty', []), 4) + ci
                + tag('SerializedSaveGames', ('ArrayProperty', [('StructProperty', [])]), len(ssg_payload)) + ssg_payload + NONE)
        sav = b'GSWU' + b'\x00' * 12 + b'GVAS-header' + body

        with mock.patch.object(sn2patch, 'oodle_dec', lambda src, usize: bytes(src)), \
             mock.patch.object(sn2patch, 'oodle_comp', lambda raw: bytes(raw)), \
             tempfile.TemporaryDirectory() as t:
            src, dst = os.path.join(t, 'in.sav'), os.path.join(t, 'out.sav')
            open(src, 'wb').write(sav)
            report = sn2patch.patch_file(src, dst, ['DA_P'], ['DA_X'])
            out = open(dst, 'rb').read()
            self.assertEqual(open(src, 'rb').read(), sav)  # input untouched

            i = out.find(b'\x0e\x00\x00\x00ContainerInfo\x00')
            top, end = sn2goals.props(out, i, len(out))
            self.assertEqual(end, len(out))
            ss = [x for x in top if x['name'] == 'SerializedSaveGames'][0]
            p = ss['payload'] + 4
            streams = []
            for _ in range(2):
                vals, p = sn2goals.props(out, p, ss['next'])
                inner, _ = sn2goals.props(out, vals[0]['payload'], vals[0]['next'])
                cnt = struct.unpack_from('<i', out, inner[0]['payload'])[0]
                s = inner[0]['payload'] + 4
                streams.append(sn2patch.decode_buffer(out, s, s + cnt))
            self.assertEqual(p, ss['next'])

        self.assertEqual(sorted(r[0] for r in report), [0, 1])
        self.assertEqual(goal_names(streams[0], PLAYER), ['DA_A', 'DA_P'])
        self.assertEqual(goal_names(streams[0], WORLD), ['DA_W', 'DA_X'])
        self.assertEqual(goal_names(streams[1], PLAYER), ['DA_P'])
        self.assertEqual(goal_names(streams[1], WORLD), ['DA_X'])


if __name__ == '__main__':
    unittest.main()
