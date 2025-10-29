#!/usr/bin/env python3
import argparse, json, re, sys
from pathlib import Path
import cutie
import xml.etree.cElementTree as ET

# Built from dir_info_with_files_trimmed.json from https://github.com/CSharpM7/reslotter
ALLOWED_EXTENSIONS = {
    ".adjb", ".arc", ".bin", ".bntx", ".eff", ".h264", ".lc", ".lvd", ".nro",
    ".nuanmb", ".nuhlpb", ".numatb", ".numdlb", ".numshb", ".numshexb",
    ".nus3audio", ".nus3bank", ".nusktb", ".nusrcmdlb", ".nutexb", ".prc",
    ".shpc", ".shpcanim", ".sqb", ".stdat", ".stprm", ".tonelabel", ".xmb"
}
SOUND_EXTS = [".nus3audio", ".nus3bank", ".tonelabel"]
# Built from CSK Alt Generator source code
UI_NAMES = {'battlefield_l': 'BattleFieldL', 'battlefield_s': 'BattleFieldS'}
UI_IS_PATCH = {'brave_altar', 'jack_mementoes', 'sp_edit', 'demon_dojo', 'ff_cave', 'buddy_spiral', 'pickel_world', 'dolly_stadium', 'xeno_alst', 'battlefield_s', 'homeruncontest', 'trail_castle', 'fe_shrine', 'tantan_spring'}
STAGE_NO_BATTLE = {"battlefield_l", "battlefield_s", "battlefield", "end"}


def is_allowed(p): return Path(p).suffix.lower() in ALLOWED_EXTENSIONS


'''
For simplicity sake, this program doesn't support multiple stages being redirected at once.
Since common folders aren't able to be redirected yet, this isn't supported either.
Because of this, we expect only 1 directory to be present in the stage folder.
'''
def find_single_stage_dir(root: Path):
    stage_dir = root / "stage"
    if not stage_dir.exists() or not stage_dir.is_dir():
        raise Exception("The selected folder does not have any stages to redirect.")
    subs = [d for d in stage_dir.iterdir() if d.is_dir()]
    if len(subs) != 1:
        raise Exception(
            "This program only supports a single folder in the stage folder. Ensure only the stage folder you wish to reslot is present.")
    return stage_dir, subs[0].name


def substitute_stage_name(path_in_current: str, current_stage: str, base_stage: str):
    parts = path_in_current.replace("\\","/").split("/")
    if len(parts) >= 3 and parts[0] == "stage" and parts[1] == current_stage:
        parts[1] = base_stage
        return "/".join(parts)
    return "/".join(parts)


# Collects all files from file_array that is part of the stage we're redirecting
def build_base_stage_files(file_array, base_stage: str):
    pref_b = f"stage/{base_stage}/battle/"
    pref_n = f"stage/{base_stage}/normal/"
    out = []
    for p in file_array:
        if p.startswith(pref_b) or p.startswith(pref_n):
            out.append(p)
    return out


# Only gathers files that have extensions that are in the base game. Prevents things like .prcxml from being edited.
def collect_all_allowed(root: Path):
    m_files = []
    for p in root.rglob("*"):
        if p.is_file():
            rel = str(p.relative_to(root)).replace("\\", "/")
            if is_allowed(rel): m_files.append(rel)
    return m_files


def in_base_dirs(cp, base_file_set):
    return any(p == cp or p.startswith(cp + "/") for p in base_file_set)


def write_config(root: Path, share_to_vanilla: dict, new_dir_files: dict, new_dir_infos: list):
    cfg_path = root / "config.json"
    data = {}
    data["share_to_vanilla"] = share_to_vanilla
    data["new-dir-files"] = new_dir_files
    data["new-dir-infos"] = new_dir_infos
    with open(cfg_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def sound_paths_for(stage_name: str):
    return [f"sound/bank/stage/se_stage_{stage_name}{ext}" for ext in SOUND_EXTS]


def ui_paths_for(stage_name: str):
    ui_paths = []
    ui_replace = "replace_patch" if stage_name in UI_IS_PATCH else "replace"
    stage_ui = UI_NAMES.get(stage_name, stage_name)
    for i in range(5):
        ui_paths.append(f"ui/{ui_replace}/stage/stage_{i}/stage_{i}_{stage_ui}.bntx")
    return ui_paths

def is_stage_sound_for(stage_name: str, path_str: str):
    return bool(
        re.fullmatch(rf"sound/bank/stage/se_stage_{re.escape(stage_name)}\.(nus3audio|nus3bank|tonelabel)", path_str))

def is_stage_eff_for(stage_name: str, path_str: str):
    return f"effect/stage/{stage_name}/ef_{stage_name}.eff" == path_str


def add_dir_with_parents(d: str, base_file_set: set, new_dir_infos_set: set, new_dir_infos: list):
    p = Path(d)
    while True:
        ds = str(p).replace("\\", "/")
        if ds and ds != "." and ds not in new_dir_infos_set and not in_base_dirs(ds, base_file_set):
            new_dir_infos.append(ds)
            new_dir_infos_set.add(ds)
        if not p.parts: break
        p = p.parent
        if str(p) == "" or str(p) == ".": break


def build_base_dir_infos(tree_root, base_stage, current_stage):
    # Unlike fighters, stage dir infos are mostly identical to their actual file locations
    # This step is here as a precaution, just to ensure the stages are accurately replicated
    res = set()
    stage_node = (((tree_root or {}).get("directories") or {}).get("stage") or {}).get("directories") or {}
    stage_branch = stage_node.get(base_stage)

    def walk(node, prefix):
        res.add(prefix)
        dirs = node.get("directories") or {}
        for name, sub in dirs.items(): walk(sub, f"{prefix}/{name}")

    walk(stage_branch, f"stage/{current_stage}")
    return sorted(res)


def safe_rename(src: Path, dst: Path):
    if not src.exists(): return False
    if dst.exists(): return False
    dst.parent.mkdir(parents=True, exist_ok=True)
    src.rename(dst)
    return True


def rename_stage(root: Path, old: str, new: str):
    changes = []
    changes.append((root / f"effect/stage/{old}/ef_{old}.eff", root / f"effect/stage/{new}/ef_{new}.eff"))
    for ext in SOUND_EXTS:
        changes.append((root / f"sound/bank/stage/se_stage_{old}{ext}", root / f"sound/bank/stage/se_stage_{new}{ext}"))
    for i in range(5):
        changes.append((root / f"ui/replace/stage/stage_{i}/stage_{i}_{old}.bntx", root / f"ui/replace/stage/stage_{i}/stage_{i}_{new}.bntx"))
        changes.append((root / f"ui/replace_patch/stage/stage_{i}/stage_{i}_{old}.bntx", root / f"ui/replace_patch/stage/stage_{i}/stage_{i}_{new}.bntx"))
    changes.append((root / f"stage/{old}", root / f"stage/{new}"))
    done = 0
    for src, dst in changes:
        try:
            if safe_rename(src, dst): done += 1
        except Exception as e: 
            print(f"WARNING: Failed to rename {src} to {dst}!\nFile must be manually renamed!")
    return done

def user_input(input_message: str, no_input_message: str, is_numeric: bool = False):
    while True:
        m_input = input(input_message).strip()
        if is_numeric and not m_input.isnumeric():
            print(no_input_message)
        elif not m_input:
            print(no_input_message)
        else:
            break
    return int(m_input) if is_numeric else m_input
    
def user_yes_no(input_message: str):
    print(input_message)
    return ["Yes", "No"][cutie.select(["Yes", "No"])] == "Yes"
    
def app_dir() -> Path:
    # When frozen: sys.executable points to the exe on disk.
    # When running from source: __file__ points to the script.
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent

# Not my function but I can't remember where I found it
def delete_empty_dirs(path):
    # get a list of all directorys in path and subpaths
    def get_dirs(path, result=[]):
        for p in path.iterdir():
            if p.is_dir():
                result += [p]
                get_dirs(p)
        return result


    # keep trying to delete empty folders until none are left
    dirs = get_dirs(path)
    done = False
    while not done:
        done = True
        for p in dirs:
            try:
                p.rmdir()
                done = False
            except OSError:
                pass
                
# Basically just pulled this from stackoverflow
def create_stage_xmsbt(m_string: str, file_path: Path, stage_name: str):
    root = ET.Element("xmsbt")
    entry = ET.SubElement(root, "entry", label=f"nam_stg1_{stage_name}")
    text_elem = ET.SubElement(entry, "text")
    text_elem.text = m_string
    tree = ET.ElementTree(root)
    ET.indent(root, space="  ")
    
    file_path.parent.mkdir(parents=True, exist_ok=True)
    
    tree.write(file_path, encoding="utf-16")


def main():
    ap = argparse.ArgumentParser(
        description="Tool to generate a config.json and rename files from a normal stage mod to a redirected one.")
    ap.add_argument("root")
    ap.add_argument("--base",
                    default=str(app_dir() / "dir_info_with_files_trimmed.json"))
    args = ap.parse_args()

    root = Path(args.root).resolve()
    stage_dir, detected_stage = find_single_stage_dir(root)

    is_renamed = user_yes_no("Have you already renamed the files to the new stage name?")
    if is_renamed:
        base_stage = user_input("Enter the base stage to redirect (e.g., dk_waterfall): ",
                                "No base stage provided. Please input a proper stage name.\n")
        current_stage = detected_stage
    else:
        base_stage = detected_stage
        current_stage = user_input("Enter your new stage name (e.g., dk_hijinxs): ",
                                   "No new stage name was provided. Please input a proper stage name.\n")

    with open(args.base, "r", encoding="utf-8") as f:
        base_data = json.load(f)

    base_file_array = base_data.get("file_array")
    dirs_tree = base_data.get("dirs")
    if dirs_tree is None or base_file_array is None:
        raise Exception(f"Unable to obtain file_array or dirs from {args.base}. Please ensure file is valid.")

    # This shouldn't cause issues, all files are unique
    base_file_set = set(base_file_array)
    base_stage_files = build_base_stage_files(base_file_array, base_stage)

    if is_renamed:
        scanned_files = collect_all_allowed(root)
        scanned_files_base = {substitute_stage_name(p, current_stage, base_stage) for p in scanned_files}
    else:
        scanned_files_base = collect_all_allowed(root)
        scanned_files = {substitute_stage_name(p, base_stage, current_stage) for p in scanned_files_base}


    # These are the files we're going to share. Only saves the base_stage_files files that aren't on disk
    to_share = [p for p in base_stage_files if p not in scanned_files_base]

    share_to_vanilla = {}
    new_files, new_files_set = [], set()
    for share_file in to_share:
        target = share_file.replace(f"/{base_stage}/", f"/{current_stage}/")
        share_to_vanilla[share_file] = target
        if target not in base_file_set and target not in new_files_set:
            new_files.append(target)
            new_files_set.add(target)

    # Any paths not in stage are handled separately since I don't derive from dirs
    # Might change the way I handle this, especially since I derive from dirs later on. Seems redundant
    for sound_path in sound_paths_for(base_stage):
        target_sound_path = sound_path.replace(f"se_stage_{base_stage}", f"se_stage_{current_stage}")
        if sound_path in scanned_files or target_sound_path in scanned_files:
            continue
        share_to_vanilla[sound_path] = target_sound_path
        if target_sound_path not in base_file_set and target_sound_path not in new_files_set:
            new_files.append(target_sound_path)
            new_files_set.add(target_sound_path)

    for ui_path in ui_paths_for(base_stage):
        target_ui_path = ui_path.replace(f"_{base_stage}", f"_{current_stage}")
        if ui_path in scanned_files or target_ui_path in scanned_files:
            continue
        share_to_vanilla[ui_path] = target_ui_path
        if target_ui_path not in base_file_set and target_ui_path not in new_files_set:
            new_files.append(target_ui_path)
            new_files_set.add(target_ui_path)

    eff_path = f"effect/stage/{base_stage}/ef_{base_stage}.eff"
    target_eff_path = f"effect/stage/{current_stage}/ef_{current_stage}.eff"
    if eff_path not in scanned_files and target_eff_path not in scanned_files:
        share_to_vanilla[eff_path] = target_eff_path
        if target_eff_path not in base_file_set and target_eff_path not in new_files_set:
            new_files.append(target_eff_path)
            new_files_set.add(target_eff_path)

    for f in scanned_files:
        if f not in base_file_set and f not in new_files_set:
            new_files.append(f)
            new_files_set.add(f)
        

    new_dir_files, new_dir_infos, new_dir_infos_set = {}, [], set()

    base_dir_infos = build_base_dir_infos(dirs_tree, base_stage, current_stage)
    for d in base_dir_infos:
        if d not in new_dir_infos_set:
            new_dir_infos.append(d)
            new_dir_infos_set.add(d)

    sound_key_normal = f"stage/{current_stage}/normal/sound"
    sound_key_battle = f"stage/{current_stage}/battle/sound"

    for f in new_files:
        if is_stage_sound_for(current_stage, f):
            new_dir_files.setdefault(sound_key_normal, [])
            new_dir_files.setdefault(sound_key_battle, [])
            if f not in new_dir_files[sound_key_normal]: new_dir_files[sound_key_normal].append(f)
            if f not in new_dir_files[sound_key_battle]: new_dir_files[sound_key_battle].append(f)
            add_dir_with_parents(sound_key_normal, base_file_set, new_dir_infos_set, new_dir_infos)
            add_dir_with_parents(sound_key_battle, base_file_set, new_dir_infos_set, new_dir_infos)
        else:
            if "ui/" in f: continue # UI isn't necessary to add it seems
            parent_dir = str(Path(f).parent).replace("\\", "/")
            if parent_dir and parent_dir != ".":
                lst = new_dir_files.setdefault(parent_dir, [])
                if f not in lst: lst.append(f)
            add_dir_with_parents(parent_dir, base_file_set, new_dir_infos_set, new_dir_infos)

    write_config(root, share_to_vanilla, new_dir_files, new_dir_infos)
    print("Config.json updated")
    if not is_renamed:
        rename_stage(root, base_stage, current_stage)
        print(f"Stage files renamed from {base_stage} to {current_stage}")
    delete_empty_dirs(root)
    
    is_add_xmsbt = user_yes_no("\nDo you want to generate a xmsbt file (for the stage's in-game name)?\nNote that this will overwrite your current msg_name.xmsbt if it's present.")
    if is_add_xmsbt:
        stage_msbt_name = user_input("Enter the stage's display name: ", "No name was entered, please enter a name")
        xmsbt_path = root / "ui" / "message" / "msg_name.xmsbt"
        create_stage_xmsbt(stage_msbt_name, root / "ui" / "message" / "msg_name.xmsbt", current_stage)
        print(f"File written to {str(xmsbt_path)}")
        
    is_create_database = user_yes_no(f"\nDo you want to generate a database json for your stage?\nIt will be named {current_stage}.json in the database folder.")
    if is_create_database:
        database_path = root / "database" / f"{current_stage}.json"
        database_json = {}
        database_json["stage_database_entries"] = [{   
        "ui_stage_id": f"ui_stage_{current_stage}",
        "clone_from_ui_stage_id": f"ui_stage_{base_stage}",
        "name_id": current_stage,
        "disp_order": 127,
		"is_dlc": False
        }]
        bgm_name = input("Type in the bgm name that will be used (or leave blank to use default): ")
        
        if bgm_name != "":
            database_json["stage_database_entries"][0]["bgm_set_id"] = bgm_name
            playlist_number = user_input("Enter the playlist number to use: ", "Input was not a number. Please enter a valid number", True)
            database_json["stage_database_entries"][0]["bgm_setting_no"] = playlist_number
        series_name = input("Type in the series name that will be used (or leave blank to use default): ")
        if series_name != "":
            database_json["stage_database_entries"][0]["ui_series_id"] = series_name
        
        stage_mapping = {"normal": "normal", "end_": "battle", "battle_": "battle"}
        if base_stage in STAGE_NO_BATTLE: 
            stage_mapping = {"normal": "normal", "end_": "normal", "battle_": "normal"}
            database_json["stage_database_entries"][0]["stage_place_id"] = base_stage
            database_json["stage_database_entries"][0]["secret_stage_place_id"] = base_stage
        redir_json = {}

        for k, v in stage_mapping.items():
            redir_json[f"{k.replace('normal', '')}{base_stage}"] = [
                {
                    "ui_stage_id": f"ui_stage_{current_stage}",
                    "resources": {
                        k.replace("_", ""): {
                            "stage_load_group_hash": f"stage/{current_stage}/{v}",
                            "effect_load_group_hash": f"effect/stage/{current_stage}",
                            "nus3bank_path_hash": f"sound/bank/stage/se_stage_{current_stage}.nus3bank",
                            "sqb_path_hash": "0x27ad9b4322",
                            "nus3audio_path_hash": f"sound/bank/stage/se_stage_{current_stage}.nus3audio",
                            "tonelabel_path_hash": f"sound/bank/stage/se_stage_{current_stage}.tonelabel"
                        }
                    }
                }
            ]
        database_json["stage_resource_redirection_entries"] = redir_json
        database_path.parent.mkdir(parents=True, exist_ok=True)
        with open(database_path, "w", encoding="utf-8") as f:
            json.dump(database_json, f, indent=2)
        print(f"File written to {str(database_path)}")

        


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("\nAn error occurred:")
        print(e)
    input("\nPress Enter to exit...")
