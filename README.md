# sn2-save-tools

Python scripts for reading and patching Subnautica 2 save files (`.sav`). The main use is adding story goals to a save when a quest flag never fired and the game is stuck.

This is an unofficial fan tool. It is not affiliated with or endorsed by Unknown Worlds or Krafton.

## Warning

Patching a save can corrupt it. Always work on a copy and keep the original somewhere safe.

The tools were written against Subnautica 2 on Unreal Engine 5.6, Steam build 128456. The game is in early access and its save format can change with any update. If you are on a different build, expect things to break, and check the output of `sn2goals.py` before you trust a patched file.

## Back up your save first

On Windows, saves are in:

```
%LOCALAPPDATA%\Subnautica2\Saved\SaveGames\savegame_N.sav
```

Close the game (or sit at the main menu) before copying or replacing anything. Copy the whole `SaveGames` folder somewhere outside the game's directories. `sn2patch.py` never edits its input, and refuses to write over it, but that does not protect you from copying the wrong file back.

## Requirements

- Python 3.9 or newer. No third-party Python packages.
- For `sn2blob.py`: an [ooz](https://github.com/powzix/ooz) binary, on your `PATH` or pointed to by `SN2_OOZ`.
- For `sn2patch.py`: the Oodle shared library `liboo2corelinux64.so.9`, on the library path or pointed to by `SN2_OODLE_LIB`. Oodle is proprietary and is not included here. It ships with Unreal Engine and some other software, so you need to find your own copy. The patcher uses the real library for compression because it round-trips reliably.

The scripts were run on Linux. On Windows you would need a matching Oodle DLL, and the `ctypes` loading in `sn2patch.py` would need adjusting.

## Usage

Dump every decompressed block from a save:

```
python3 sn2blob.py savegame_0.sav out/
```

List the story-goal containers in a decompressed GameData stream (one of the `.bin` files from the step above):

```
python3 sn2goals.py out/blob_001_12345.bin
```

Add story goals and write a new save:

```
python3 sn2patch.py savegame_0.sav savegame_0.patched.sav \
  --player DA_Some_Player_StoryGoal \
  --world DA_Some_World_StoryGoal
```

`--player` and `--world` can each be given more than once. Goals that are already present are skipped. The patch is applied to both save blobs (current and previous checkpoint).

`storygoals.txt` lists all 1,403 `UWEStoryGoal` asset names from the LabrynthKing/SN2-SDK dump, so you can look up the exact name you need.

`ueprops.py` is a small property-tag walker. `python3 ueprops.py STREAM.bin OFFSET` prints the tagged properties starting at an offset, which helps when you are exploring a new part of the file.

## Example: the Tadpole Pens keycode door

The patcher was first used on a save where the Tadpole Pens keycode door would not open. The fix added these goals:

```
python3 sn2patch.py savegame_0.sav savegame_0.patched.sav \
  --player DA_StoryGoal_Key_Kurultai \
  --player DA_Storygoal_Player_Key_Ch2_TadpoleBase_StoryGoal \
  --world DA_StoryGoal_Key_Kurultai_WorldStoryGoal
```

After copying the patched file back in place of the original, the door opened. Your save may be stuck on a different goal, so treat this as an example of the process rather than a fix to apply blindly.

## Save format notes

- The file starts with a 16-byte `GSWU` wrapper, followed by a plain GVAS body (`UWESaveGameCollection`).
- `SerializedSaveGames[]` holds two `UWESaveBlob`s. Index 0 is the current save and index 1 is the previous checkpoint.
- Each blob has `MetaData` and `GameData` buffers. Their `Data` byte arrays are back-to-back UE `SerializeCompressed` v2 blocks: tag `C1 83 2A 9E 22 22 22 22`, chunk size 131072, and format byte `02` for Oodle Kraken.
- Decompressed GameData is `int32 len, u8 0`, then tagged properties in the UE 5.4+ format, where each tag carries a type-name tree instead of a flat type name.
- `SaveData` is a `Map<Guid, UWESaveBuffer>`. Story goals live in two of its entries:
  - player container, guid `fe4336a9ca3953a0158d8f9583b9defd`
  - world container, guid `a51739146e3bae4f91fa5aa2a192c919`
- Each container holds `StoryGoals.Entries[]` of `UWEStoryGoalEntry{StoryGoal: PrimaryAssetId}`.

When the patcher inserts entries, it updates every enclosing size and count: the `Entries` array, the `StoryGoals` struct, the container's `Data` byte count, `SaveData`, the stream length prefix, and then the outer `GameData` and `SerializedSaveGames` sizes after recompression.

## Without editing files

If you would rather not touch the save file, UE4SS (Nexus Mods mod 36) plus the Console Commands mod (mod 41) let you press F2 and run `ToggleStoryGoal <DA_name>`, or `ToggleDiagnostic StoryGoal` for a clickable list.

## Tests

```
python3 -m unittest discover -s tests -v
```

The tests build synthetic save data in memory and stub out compression, so they need neither real saves nor Oodle.

## License

MIT. See [LICENSE](LICENSE).
