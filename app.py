from pathlib import Path
import json, subprocess, sys, os, zipfile, tempfile, shutil, stat, re
import gradio as gr
from engine.project_tools import FILES, write_inputs, validate, make_verification, make_manifest, export_zip

ROOT = Path(__file__).resolve().parent
DATA, PROJECTS = ROOT / "data", ROOT / "projects"
SCHEMA_BUNDLE = DATA / "schemas_v0_1.json"
BENCHMARK_BUNDLE = DATA / "benchmark_capacitor_v0_1.json"
PROJECTS.mkdir(exist_ok=True)
SPEC_COLUMNS=["scene_id","start_seconds","end_seconds","duration_seconds","background_asset","content_image_asset","image_fit","image_motion","technical_rules"]

def default_bundle():
    return json.loads(BENCHMARK_BUNDLE.read_text(encoding="utf-8"))

def rows(value, columns):
    if value is None: return []
    if hasattr(value, "to_dict"): value = value.to_dict(orient="records")
    if isinstance(value, dict): value = [value]
    result = []
    for row in value:
        item = row if isinstance(row, dict) else dict(zip(columns, row))
        if any(v not in (None, "") for v in item.values()): result.append(item)
    return result

def csv(value):
    if isinstance(value, list): return value
    return [x.strip() for x in str(value or "").replace("\n", ",").split(",") if x.strip()]

def meta(name, pid):
    return {"schema_name": name, "schema_version": "0.1.0", "project_id": str(pid).strip() or "PROJECT"}

def form_to_texts(*v):
    (pid, topic, objective, audience, platform, aspect, target_duration, language,
     facts, forbidden, rules, visual_language, background, highlight, motion,
     story_total, storyboard, scene_specs, assets, narration,
     width, height, fps, render_duration, container, codec,
     safe_top, safe_bottom, safe_left, safe_right, seed, fixed_frames, filename,
     audio_source, audio_file, scene_audio_map, voice_type, custom_voice, audio_volume,
     reference_url, duration_error, overall_status, blocker_violations,
     asset_uploads, scene_image_uploads) = v
    pid = str(pid).strip() or "PROJECT"
    fact_rows = rows(facts, ["fact_id", "claim"])
    rule_rows = rows(rules, ["rule_id", "severity", "assertion"])
    story_rows = rows(storyboard, ["scene_id", "start_seconds", "end_seconds", "duration_seconds", "narration_draft"])
    spec_rows = rows(scene_specs,SPEC_COLUMNS)
    asset_rows=rows(assets,["asset_id","source_type","source_value"])
    for asset in asset_rows:
        asset["source_type"]=asset.get("source_type") or "built_in_grid"
        asset["source_value"]=asset.get("source_value") or ("engineering_grid" if asset["source_type"]=="built_in_grid" else "")
    narration_rows=rows(narration,["scene_id"])
    for segment in narration_rows:
        sid=segment.get("scene_id")
        if sid in (scene_audio_map or {}):
            suffix=Path(scene_audio_map[sid]).suffix.lower() or ".wav"
            segment["audio_file"]=f"audio/scenes/{clean_id(sid,'SCENE')}{suffix}"
            segment["audio_status"]="RECORDED"
    for item in story_rows:
        for key in ("start_seconds", "end_seconds", "duration_seconds"): item[key] = float(item.get(key) or 0)
    for item in spec_rows:
        for key in ("start_seconds", "end_seconds", "duration_seconds"): item[key] = float(item.get(key) or 0)
        item["technical_rules"], item["objects"] = csv(item.get("technical_rules")), []
        item["content_image_asset"]=str(item.get("content_image_asset") or "").strip()
        item["image_fit"]=item.get("image_fit") or "contain"
        item["image_motion"]=item.get("image_motion") or "none"
    bundle = {
      FILES[0]: {"_meta":meta("project_input",pid),"topic":topic,"objective":objective,"audience":{"level":audience},"platform":{"name":platform,"aspect_ratio":aspect},"duration":{"target_seconds":float(target_duration)},"language":language},
      FILES[1]: {"_meta":meta("technical_truth",pid),"facts":fact_rows,"forbidden_visuals":csv(forbidden),"qa_rules":rule_rows},
      FILES[2]: {"_meta":meta("benchmark_style",pid),"visual_language":visual_language,"background":background,"highlight":highlight,"motion_grammar":csv(motion)},
      FILES[3]: {"_meta":meta("storyboard",pid),"total_duration_seconds":float(story_total),"scenes":story_rows},
      FILES[4]: {"_meta":meta("scene_spec",pid),"scenes":spec_rows},
      FILES[5]: {"_meta":meta("asset_manifest",pid),"assets":asset_rows},
      FILES[6]: {"_meta":meta("narration_timing",pid),"segments":narration_rows},
      FILES[7]: {"_meta":meta("render_config",pid),"video":{"width":int(width),"height":int(height),"fps":int(fps),"duration_seconds":float(render_duration),"container":container,"video_codec":codec},"safe_zone":{"top":int(safe_top),"bottom":int(safe_bottom),"left":int(safe_left),"right":int(safe_right)},"determinism":{"random_seed":int(seed),"fixed_frame_count":int(fixed_frames)},"output":{"filename":filename},"audio":{"source":audio_source,"uploaded_filename":Path(audio_file).name if audio_file else None,"scene_recordings":[{"scene_id":sid,"filename":f"{clean_id(sid,'SCENE')}{Path(path).suffix.lower() or '.wav'}"} for sid,path in (scene_audio_map or {}).items()],"voice_type":voice_type,"custom_voice":custom_voice or "","volume":float(audio_volume)}},
      FILES[8]: {"_meta":meta("verification_report",pid),"reference":{"url":reference_url},"acceptance_thresholds":{"duration_error_seconds_max":float(duration_error)},"results":{"overall_status":overall_status,"blocker_violations":csv(blocker_violations)}}
    }
    return [json.dumps(bundle[f], indent=2, ensure_ascii=False) for f in FILES]

def bundle_to_form(bundle):
    p,t,s,story,spec,a,n,cfg,ver = [bundle[f] for f in FILES]
    video, safe, det, audio = cfg.get("video",{}), cfg.get("safe_zone",{}), cfg.get("determinism",{}), cfg.get("audio",{})
    return (
      p.get("_meta",{}).get("project_id","PROJECT"),p.get("topic",""),p.get("objective",""),p.get("audience",{}).get("level","beginner"),p.get("platform",{}).get("name","youtube_shorts"),p.get("platform",{}).get("aspect_ratio","9:16"),p.get("duration",{}).get("target_seconds",60),p.get("language","en"),
      [[x.get("fact_id",""),x.get("claim","")] for x in t.get("facts",[])],"\n".join(t.get("forbidden_visuals",[])),[[x.get("rule_id",""),x.get("severity","major"),x.get("assertion","")] for x in t.get("qa_rules",[])],
      s.get("visual_language",""),s.get("background",""),s.get("highlight","yellow"),s.get("motion_grammar",[]),story.get("total_duration_seconds",60),
      [[x.get("scene_id",""),x.get("start_seconds",0),x.get("end_seconds",0),x.get("duration_seconds",0),x.get("narration_draft","")] for x in story.get("scenes",[])],
      [[x.get("scene_id",""),x.get("start_seconds",0),x.get("end_seconds",0),x.get("duration_seconds",0),x.get("background_asset",""),x.get("content_image_asset",""),x.get("image_fit","contain"),x.get("image_motion","none"),", ".join(x.get("technical_rules",[]))] for x in spec.get("scenes",[])],
      [[x.get("asset_id",""),x.get("source_type","built_in_grid"),x.get("source_value","engineering_grid" if x.get("source_type","built_in_grid")=="built_in_grid" else "")] for x in a.get("assets",[])],[[x.get("scene_id","")] for x in n.get("segments",[])],
      video.get("width",1080),video.get("height",1920),video.get("fps",30),video.get("duration_seconds",60),video.get("container","mp4"),video.get("video_codec","h264"),safe.get("top",150),safe.get("bottom",320),safe.get("left",80),safe.get("right",190),det.get("random_seed",17012023),det.get("fixed_frame_count",1800),cfg.get("output",{}).get("filename","PROJECT_final.mp4"),
      audio.get("source","generated_voice"),None,{},audio.get("voice_type","female"),audio.get("custom_voice",""),audio.get("volume",1.0),
      ver.get("reference",{}).get("url",""),ver.get("acceptance_thresholds",{}).get("duration_error_seconds_max",2),ver.get("results",{}).get("overall_status","NOT_RUN"),"\n".join(ver.get("results",{}).get("blocker_violations",[])),None,None)

def stage_audio(project, audio_file):
    """Copy an uploaded track into the project so renders and exports are portable."""
    if not audio_file: return None
    source=Path(audio_file); audio_dir=project/"input"/"audio"; audio_dir.mkdir(parents=True,exist_ok=True)
    target=audio_dir/source.name
    if source.resolve()!=target.resolve():
        import shutil
        shutil.copy2(source,target)
    return target

def upload_paths(files):
    if not files: return []
    if not isinstance(files,(list,tuple)): files=[files]
    return [Path(getattr(file,"name",file)) for file in files if file]

def stage_background_assets(project, files):
    target_dir=project/"input"/"assets"; target_dir.mkdir(parents=True,exist_ok=True); staged=[]
    for source in upload_paths(files):
        if not source.is_file(): continue
        target=target_dir/source.name
        if source.resolve()!=target.resolve(): shutil.copy2(source,target)
        staged.append(str(target))
    return staged

def stage_scene_images(project, files):
    target_dir=project/"input"/"scene_images"; target_dir.mkdir(parents=True,exist_ok=True); staged=[]
    for source in upload_paths(files):
        if not source.is_file(): continue
        target=target_dir/source.name
        if source.resolve()!=target.resolve(): shutil.copy2(source,target)
        staged.append(str(target))
    return staged

def register_scene_images(project_id, files, asset_table, scene_specs):
    asset_rows=rows(asset_table,["asset_id","source_type","source_value"]); existing={str(row.get("asset_id","")) for row in asset_rows}; registered=[]; stored_paths=[]
    image_ext={".png",".jpg",".jpeg",".webp",".bmp"}; target_dir=project_from_id(project_id)/"input"/"scene_images"; target_dir.mkdir(parents=True,exist_ok=True); occurrences={}
    for path in upload_paths(files):
        suffix=path.suffix.lower()
        if suffix not in image_ext: continue
        source_match=next((row for row in asset_rows if row.get("source_type")=="content_image" and row.get("source_value")==path.name),None)
        if source_match:
            registered.append(source_match["asset_id"]); stored_paths.append(str(path)); continue
        base="image_"+clean_id(path.stem,"scene"); occurrences[base]=occurrences.get(base,0)+1; asset_id=base; counter=2
        if path.parent.resolve()==target_dir.resolve():
            while asset_id in existing: asset_id=f"{base}_{counter}"; counter+=1
            asset_rows.append({"asset_id":asset_id,"source_type":"content_image","source_value":path.name}); existing.add(asset_id); registered.append(asset_id); stored_paths.append(str(path)); continue
        existing_match=next((row for row in asset_rows if row.get("asset_id")==base and row.get("source_value")==f"{base}{suffix}"),None)
        if occurrences[base]==1 and existing_match:
            target=target_dir/f"{base}{suffix}"
            if path.resolve()!=target.resolve(): shutil.copy2(path,target)
            registered.append(base); stored_paths.append(str(target)); continue
        while asset_id in existing: asset_id=f"{base}_{counter}"; counter+=1
        stored_name=f"{asset_id}{suffix}"; target=target_dir/stored_name
        if path.resolve()!=target.resolve(): shutil.copy2(path,target)
        asset_rows.append({"asset_id":asset_id,"source_type":"content_image","source_value":stored_name}); existing.add(asset_id); registered.append(asset_id); stored_paths.append(str(target))
    spec_rows=rows(scene_specs,SPEC_COLUMNS)
    open_scene_indexes=[index for index,row in enumerate(spec_rows) if not str(row.get("content_image_asset") or "").strip()]
    assigned_assets={str(row.get("content_image_asset") or "").strip() for row in spec_rows if str(row.get("content_image_asset") or "").strip()}
    remaining=[asset_id for asset_id in registered if asset_id not in assigned_assets]; assigned=0
    for index in list(open_scene_indexes):
        prefix="image_"+clean_id(spec_rows[index].get("scene_id"),"scene").lower()
        match=next((asset_id for asset_id in remaining if asset_id.lower()==prefix or asset_id.lower().startswith(prefix+"_") or asset_id.lower().startswith(prefix+"-")),None)
        if match:
            spec_rows[index]["content_image_asset"]=match; spec_rows[index]["image_fit"]=spec_rows[index].get("image_fit") or "contain"; spec_rows[index]["image_motion"]=spec_rows[index].get("image_motion") or "none"; remaining.remove(match); assigned+=1
    open_scene_indexes=[index for index,row in enumerate(spec_rows) if not str(row.get("content_image_asset") or "").strip()]
    for index,asset_id in zip(open_scene_indexes,remaining):
        spec_rows[index]["content_image_asset"]=asset_id; spec_rows[index]["image_fit"]=spec_rows[index].get("image_fit") or "contain"; spec_rows[index]["image_motion"]=spec_rows[index].get("image_motion") or "none"; assigned+=1
    table_values=[[row.get("asset_id",""),row.get("source_type",""),row.get("source_value","")] for row in asset_rows]
    spec_values=[[row.get(column,"") for column in SPEC_COLUMNS] for row in spec_rows]
    message=(f"✅ Stored/found {len(registered)} scene image(s) and assigned {assigned}. Scene-ID filenames were matched first; remaining images followed upload/folder order." if registered else "No new supported scene images were registered.")
    if len(registered)>assigned: message+=f" {len(registered)-assigned} image(s) remain registered but unassigned because there are no empty scene slots."
    return table_values,spec_values,message,stored_paths

def scan_scene_image_folder(project_id, asset_table, scene_specs):
    folder=project_from_id(project_id)/"input"/"scene_images"; folder.mkdir(parents=True,exist_ok=True)
    def natural_key(path): return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)",path.name)]
    supported={".png",".jpg",".jpeg",".webp",".bmp"}; files=sorted((path for path in folder.iterdir() if path.is_file() and path.suffix.lower() in supported),key=natural_key)
    table,specs,message,_=register_scene_images(project_id,[str(path) for path in files],asset_table,scene_specs)
    return table,specs,(message if files else f"No supported images found in `{folder}`.")

def register_background_uploads(project_id, files, asset_table):
    asset_rows=rows(asset_table,["asset_id","source_type","source_value"]); existing={str(row.get("asset_id","")) for row in asset_rows}; added=[]
    image_ext={".png",".jpg",".jpeg",".webp",".bmp"}; video_ext={".mp4",".mov",".mkv",".webm",".avi",".m4v"}; occurrences={}
    target_dir=project_from_id(project_id)/"input"/"assets"; target_dir.mkdir(parents=True,exist_ok=True)
    for path in upload_paths(files):
        suffix=path.suffix.lower()
        if suffix not in image_ext|video_ext: continue
        base=clean_id(path.stem,"background"); occurrences[base]=occurrences.get(base,0)+1; asset_id=base; counter=2
        if occurrences[base]==1 and any(row.get("asset_id")==base and row.get("source_value")==f"{base}{suffix}" for row in asset_rows): continue
        while asset_id in existing:
            asset_id=f"{base}_{counter}"; counter+=1
        stored_name=f"{asset_id}{suffix}"; target=target_dir/stored_name
        if path.resolve()!=target.resolve(): shutil.copy2(path,target)
        asset_rows.append({"asset_id":asset_id,"source_type":"external_image" if suffix in image_ext else "external_video","source_value":stored_name}); existing.add(asset_id); added.append(asset_id)
    message=f"✅ Registered background asset IDs: {', '.join(added)}" if added else "No new supported background files were registered."
    return [[row.get("asset_id",""),row.get("source_type",""),row.get("source_value","")] for row in asset_rows],message

def add_portal_background(asset_id, source_type, primary, secondary, asset_table):
    asset_id=clean_id(asset_id,"portal_background"); asset_rows=rows(asset_table,["asset_id","source_type","source_value"])
    source_value="engineering_grid" if source_type=="built_in_grid" else (primary if source_type=="solid_color" else f"{primary},{secondary}")
    replacement={"asset_id":asset_id,"source_type":source_type,"source_value":source_value}; found=False
    for index,row in enumerate(asset_rows):
        if row.get("asset_id")==asset_id: asset_rows[index]=replacement; found=True; break
    if not found: asset_rows.append(replacement)
    return [[row.get("asset_id",""),row.get("source_type",""),row.get("source_value","")] for row in asset_rows],f"✅ {'Updated' if found else 'Added'} portal background `{asset_id}`."

def apply_background_to_scenes(asset_id, scene_specs):
    if not str(asset_id or "").strip(): return scene_specs,"❌ Enter an asset ID first."
    spec_rows=rows(scene_specs,SPEC_COLUMNS)
    for row in spec_rows: row["background_asset"]=str(asset_id).strip()
    values=[[row.get(column,"") for column in SPEC_COLUMNS] for row in spec_rows]
    return values,f"✅ Applied `{asset_id}` to {len(values)} scene(s)."

def update_background_choices(asset_table, current):
    ids=[row.get("asset_id") for row in rows(asset_table,["asset_id","source_type","source_value"]) if row.get("asset_id") and row.get("source_type")!="content_image"]
    value=current if current in ids else (ids[0] if ids else None)
    return gr.update(choices=ids,value=value)

def asset_location_status(project_id):
    project=clean_id(project_id,"PROJECT")
    return (f"**Image storage for this project**  \n"
            f"Repository folder: `projects/{project}/input/assets/`  \n"
            f"Docker folder: `/app/projects/{project}/input/assets/`  \n"
            "Use the uploader below and click **Register uploaded files**; the app copies the files into this folder automatically.")

def scene_image_location_status(project_id):
    project=clean_id(project_id,"PROJECT")
    return (f"**Main scene-image storage for this project**  \n"
            f"Repository folder: `projects/{project}/input/scene_images/`  \n"
            f"Docker folder: `/app/projects/{project}/input/scene_images/`  \n"
            "Upload images below; they are copied here and assigned to scene IDs in upload order.")

def audio_timing_status(audio_file, video_duration):
    target=float(video_duration or 0)
    if not audio_file:
        return f"Target recording length: **{target:.2f} seconds**. Record or upload audio to measure it."
    try:
        raw=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(audio_file)],text=True)
        actual=float(raw.strip()); difference=actual-target
        if abs(difference)<0.01: action="No timing adjustment is needed."
        elif difference<0: action=f"The renderer will add {abs(difference):.2f} seconds of silence at the end."
        else: action=f"The renderer will trim {difference:.2f} seconds from the end."
        return f"Recorded audio: **{actual:.2f}s** · Video: **{target:.2f}s**. {action} Final main audio length: **{target:.2f}s**."
    except Exception as e:
        return f"Could not measure this audio file: {e}"

def clean_id(value, fallback="ITEM"):
    cleaned="".join(c if c.isalnum() or c in "-_" else "_" for c in str(value or ""))[:80]
    return cleaned or fallback

def project_from_id(project_id):
    return PROJECTS/clean_id(project_id,"PROJECT")

def storyboard_rows(storyboard):
    result=rows(storyboard,["scene_id","start_seconds","end_seconds","duration_seconds","narration_draft"])
    for item in result:
        for key in ("start_seconds","end_seconds","duration_seconds"): item[key]=float(item.get(key) or 0)
    return result

def probe_audio_duration(path):
    raw=subprocess.check_output(["ffprobe","-v","error","-show_entries","format=duration","-of","default=nw=1:nk=1",str(path)],text=True)
    return float(raw.strip())

def scene_timing_status(scene_id, storyboard):
    scenes=storyboard_rows(storyboard)
    scene=next((s for s in scenes if s["scene_id"]==scene_id),None)
    if not scene: return "Select a scene to see its recording target."
    return (f"### Recording {scene['scene_id']} · {scene['start_seconds']:.2f}s–{scene['end_seconds']:.2f}s "
            f"· target **{scene['duration_seconds']:.2f}s**\n\nNarration: {scene.get('narration_draft','')}")

def validate_scene_ids(scenes):
    ids=[str(scene.get("scene_id","")).strip() for scene in scenes]
    duplicates=sorted({sid for sid in ids if ids.count(sid)>1})
    if not all(ids): raise ValueError("Every storyboard scene needs a scene ID before recording audio.")
    if duplicates: raise ValueError("Scene IDs must be unique before recording audio: "+", ".join(duplicates))

def scene_timeline_rows(storyboard, scene_audio_map):
    state=scene_audio_map or {}; timeline=[]
    for scene in storyboard_rows(storyboard):
        sid=scene["scene_id"]; path=state.get(sid); recorded=""
        if path and Path(path).is_file():
            try:
                actual=probe_audio_duration(path); recorded=f"{actual:.2f}s"; delta=actual-float(scene["duration_seconds"])
                if abs(delta)<0.01: status="✅ Exact"
                elif delta<0: status=f"🟡 Short · pads {abs(delta):.2f}s"
                else: status=f"🟡 Long · trims {delta:.2f}s"
            except Exception: recorded="unreadable"; status="❌ Invalid audio"
        else: status="⬜ Not recorded"
        timeline.append([sid,f"{scene['start_seconds']:.2f}s",f"{scene['end_seconds']:.2f}s",f"{scene['duration_seconds']:.2f}s",recorded,status])
    return timeline

def stage_scene_audio(project, scene_audio_map):
    staged={}; target_dir=project/"input"/"audio"/"scenes"; target_dir.mkdir(parents=True,exist_ok=True)
    for sid,path in (scene_audio_map or {}).items():
        source=Path(path)
        if not source.is_file(): continue
        suffix=source.suffix.lower() or ".wav"; target=target_dir/f"{clean_id(sid,'SCENE')}{suffix}"
        if source.resolve()!=target.resolve(): shutil.copy2(source,target)
        staged[str(sid)]=str(target)
    return staged

def assemble_scene_audio(project_id, storyboard, scene_audio_map, require_all=False):
    scenes=storyboard_rows(storyboard); validate_scene_ids(scenes)
    if not scenes: raise ValueError("Add at least one storyboard scene before recording audio.")
    project=project_from_id(project_id); project.mkdir(parents=True,exist_ok=True)
    staged=stage_scene_audio(project,scene_audio_map); missing=[s["scene_id"] for s in scenes if s["scene_id"] not in staged]
    if require_all and missing: raise ValueError("Record audio for every scene. Missing: "+", ".join(missing))
    work=project/"input"/"audio"/"scene_mix"; work.mkdir(parents=True,exist_ok=True); parts=[]
    for index,scene in enumerate(scenes):
        sid=scene["scene_id"]; duration=max(0.001,float(scene["duration_seconds"])); part=work/f"{index:03d}_{clean_id(sid,'SCENE')}.wav"
        if sid in staged:
            subprocess.run(["ffmpeg","-y","-loglevel","error","-i",staged[sid],"-vn","-af",f"apad,atrim=0:{duration},aresample=48000","-ar","48000","-ac","2",str(part)],check=True)
            parts.append((part,max(0,float(scene["start_seconds"]))))
    preview=project/"input"/"audio"/"per_scene_narration.wav"
    total=max(float(s["end_seconds"]) for s in scenes)
    command=["ffmpeg","-y","-loglevel","error","-f","lavfi","-t",str(total),"-i","anullsrc=r=48000:cl=stereo"]
    for part,_ in parts: command += ["-i",str(part)]
    filters=[]; mix_inputs=["[0:a]"]
    for index,(_,start) in enumerate(parts,1):
        delay=int(round(start*1000)); filters.append(f"[{index}:a]adelay={delay}|{delay}[scene{index}]"); mix_inputs.append(f"[scene{index}]")
    filters.append("".join(mix_inputs)+f"amix=inputs={len(mix_inputs)}:normalize=0:duration=first,atrim=0:{total}[mixed]")
    command += ["-filter_complex",";".join(filters),"-map","[mixed]","-ar","48000","-ac","2",str(preview)]
    subprocess.run(command,check=True)
    return str(preview),missing,staged

def save_scene_recording(project_id, scene_id, recording, storyboard, scene_audio_map):
    state=dict(scene_audio_map or {})
    if not scene_id: return state,"❌ Select a scene first.",scene_timeline_rows(storyboard,state),None,recording
    if not recording: return state,f"❌ Record or upload audio for {scene_id} first.",scene_timeline_rows(storyboard,state),None,recording
    scene=next((s for s in storyboard_rows(storyboard) if s["scene_id"]==scene_id),None)
    if not scene: return state,f"❌ {scene_id} is not present in the storyboard.",scene_timeline_rows(storyboard,state),None,recording
    project=project_from_id(project_id); source=Path(recording); target_dir=project/"input"/"audio"/"scenes"; target_dir.mkdir(parents=True,exist_ok=True)
    target=target_dir/f"{clean_id(scene_id,'SCENE')}{source.suffix.lower() or '.wav'}"
    if source.resolve()!=target.resolve(): shutil.copy2(source,target)
    state[scene_id]=str(target)
    actual=probe_audio_duration(target); preview,missing,_=assemble_scene_audio(project_id,storyboard,state)
    adjustment="exact" if abs(actual-scene["duration_seconds"])<0.01 else ("padded" if actual<scene["duration_seconds"] else "trimmed")
    message=f"✅ Saved {scene_id}: recorded {actual:.2f}s, target {scene['duration_seconds']:.2f}s ({adjustment} in the combined track)."
    if missing: message+=f" Remaining: {', '.join(missing)}."
    else: message+=" All scenes are recorded."
    return state,message,scene_timeline_rows(storyboard,state),preview,None

def clear_scene_recording(project_id, scene_id, storyboard, scene_audio_map):
    state=dict(scene_audio_map or {}); old=state.pop(scene_id,None)
    if old and Path(old).is_file(): Path(old).unlink(missing_ok=True)
    preview,_,_=assemble_scene_audio(project_id,storyboard,state)
    return state,f"Cleared the recording for {scene_id}.",scene_timeline_rows(storyboard,state),preview,None

def sync_scene_controls(storyboard, scene_audio_map):
    scenes=storyboard_rows(storyboard); choices=[(f"{s['scene_id']} · {s['start_seconds']:.2f}s–{s['end_seconds']:.2f}s · {s['duration_seconds']:.2f}s",s["scene_id"]) for s in scenes]; selected=scenes[0]["scene_id"] if scenes else None
    return gr.Dropdown(choices=choices,value=selected),scene_timeline_rows(storyboard,scene_audio_map),scene_timing_status(selected,storyboard)

def select_scene_from_timeline(storyboard, evt: gr.SelectData):
    row=getattr(evt,"row_value",None) or []
    if len(row)<2: return gr.update(),gr.update(),gr.update()
    scene_id=row[0]; start=float(str(row[1]).rstrip("s"))
    return gr.update(value=scene_id),scene_timing_status(scene_id,storyboard),gr.update(playback_position=start)

def refresh_scene_audio_ui(project_id, storyboard, scene_audio_map):
    selector,timeline,timing=sync_scene_controls(storyboard,scene_audio_map); preview=None
    count=sum(1 for path in (scene_audio_map or {}).values() if Path(path).is_file())
    if count:
        try: preview,missing,_=assemble_scene_audio(project_id,storyboard,scene_audio_map)
        except Exception as e: return selector,timeline,timing,None,f"⚠️ Could not rebuild imported scene preview: {e}"
        message=f"✅ Restored {count} scene recording(s)."
        if missing: message+=f" Still missing: {', '.join(missing)}."
    else: message="No scene recordings loaded."
    return selector,timeline,timing,preview,message

def project_dir(texts):
    try: pid=json.loads(texts[0]).get("_meta",{}).get("project_id","PROJECT")
    except Exception: pid="PROJECT"
    return project_from_id(pid)

def save_and_validate(*values):
    try:
        texts=form_to_texts(*values); p=project_dir(texts); p.mkdir(parents=True,exist_ok=True); write_inputs(p,texts); stage_audio(p,values[34]); stage_scene_audio(p,values[35]); stage_background_assets(p,values[43]); stage_scene_images(p,values[44])
        report=validate(p,SCHEMA_BUNDLE); (p/"validation_report.json").write_text(json.dumps(report,indent=2),encoding="utf-8")
        heading="✅ VALIDATION PASSED" if report["status"]=="PASS" else "❌ VALIDATION FAILED"
        return heading+"\n\n```json\n"+json.dumps(report,indent=2)+"\n```",json.dumps(report,indent=2)
    except Exception as e: return f"❌ Could not save/validate: {e}",json.dumps({"status":"FAIL","error":str(e)},indent=2)

def render_project(*values):
    texts=form_to_texts(*values); p=project_dir(texts); p.mkdir(parents=True,exist_ok=True)
    try:
        write_inputs(p,texts); audio_source=values[33]; uploaded_audio=stage_audio(p,values[34]); scene_audio_map=stage_scene_audio(p,values[35]); stage_background_assets(p,values[43]); stage_scene_images(p,values[44]); val=validate(p,SCHEMA_BUNDLE)
        if val["status"]!="PASS": return "❌ Render blocked: validation failed.",None,json.dumps(val,indent=2),"{}",None
        if audio_source=="custom_audio" and not uploaded_audio:
            return "❌ Select or record an audio file for the custom main audio track.",None,json.dumps(val,indent=2),"{}",None
        if audio_source=="per_scene_audio":
            try: uploaded_audio,_,scene_audio_map=assemble_scene_audio(json.loads(texts[0])["_meta"]["project_id"],values[16],scene_audio_map,require_all=True)
            except ValueError as e: return f"❌ {e}",None,json.dumps(val,indent=2),"{}",None
        out,logs=p/"output",p/"logs"; out.mkdir(exist_ok=True); logs.mkdir(exist_ok=True)
        env=os.environ.copy(); env["AEV_BENCH"],env["AEV_OUT"],env["AEV_LOGS"]=str(p/"input"),str(out),str(logs)
        if audio_source in {"custom_audio","per_scene_audio"}: env["AEV_AUDIO_FILE"]=str(uploaded_audio)
        proc=subprocess.run([sys.executable,str(ROOT/"engine"/"render_engine.py")],cwd=ROOT,env=env,capture_output=True,text=True)
        (logs/"renderer_stdout.txt").write_text(proc.stdout,encoding="utf-8"); (logs/"renderer_stderr.txt").write_text(proc.stderr,encoding="utf-8")
        if proc.returncode:
            error_lines=[line.strip() for line in proc.stderr.splitlines() if line.strip()]
            reason=error_lines[-1] if error_lines else "Unknown renderer error"
            return f"❌ Renderer failed: {reason}",None,json.dumps(val,indent=2),proc.stderr[-6000:],export_zip(p)
        videos=list(out.glob("*_final.mp4")); video_path=videos[0] if videos else None
        if not video_path: return "❌ Renderer produced no final MP4.",None,json.dumps(val,indent=2),proc.stdout[-6000:],export_zip(p)
        ver=make_verification(p,video_path); manifest=make_manifest(p,video_path)
        return "✅ Render complete. Project saved and bundle created.",str(video_path),json.dumps(ver,indent=2),json.dumps(manifest,indent=2),export_zip(p)
    except Exception as e:
        try: bundle=export_zip(p)
        except Exception: bundle=None
        return f"❌ Render exception: {e}",None,"{}",str(e),bundle

def export_only(*values):
    try:
        texts=form_to_texts(*values); p=project_dir(texts); p.mkdir(parents=True,exist_ok=True); write_inputs(p,texts); stage_audio(p,values[34]); stage_scene_audio(p,values[35]); stage_background_assets(p,values[43]); stage_scene_images(p,values[44])
        return export_zip(p),f"✅ Exported {p.name} assistant bundle."
    except Exception as e: return None,f"❌ Export failed: {e}"

def import_bundle(file_obj):
    if not file_obj: return (*bundle_to_form(default_bundle()),"No bundle selected.")
    try:
        tmp=Path(tempfile.mkdtemp(prefix="aev_import_"))
        with zipfile.ZipFile(Path(file_obj),"r") as z:
            for member in z.infolist():
                target=(tmp/member.filename).resolve()
                if tmp.resolve() not in target.parents and target!=tmp.resolve(): raise ValueError(f"Unsafe bundle path: {member.filename}")
                if stat.S_ISLNK(member.external_attr >> 16): raise ValueError(f"Bundle contains a symbolic link: {member.filename}")
                z.extract(member,tmp)
        bundle={}
        for name in FILES:
            found=list(tmp.rglob(name))
            if not found: raise FileNotFoundError(f"Missing {name}")
            bundle[name]=json.loads(found[0].read_text(encoding="utf-8"))
        form_values=list(bundle_to_form(bundle)); scene_map={}
        for recording in bundle[FILES[7]].get("audio",{}).get("scene_recordings",[]):
            sid=recording.get("scene_id"); filename=recording.get("filename")
            matches=list(tmp.rglob(f"audio/scenes/{filename}")) if filename else []
            if sid and not matches: matches=list(tmp.rglob(f"audio/scenes/{clean_id(sid,'SCENE')}.*"))
            if sid and matches: scene_map[sid]=str(matches[0])
        form_values[35]=stage_scene_audio(project_from_id(form_values[0]),scene_map)
        imported_assets=[str(path) for path in tmp.rglob("input/assets/*") if path.is_file()]
        form_values[43]=stage_background_assets(project_from_id(form_values[0]),imported_assets)
        imported_images=[str(path) for path in tmp.rglob("input/scene_images/*") if path.is_file()]
        form_values[44]=stage_scene_images(project_from_id(form_values[0]),imported_images)
        return (*form_values,"✅ Imported project bundle, scene recordings, scene images, and background files into the forms.")
    except Exception as e: return (*bundle_to_form(default_bundle()),f"❌ Import failed: {e}")

d=bundle_to_form(default_bundle())
with gr.Blocks(title="AI Electronics Video Tool") as demo:
    gr.Markdown("# AI Electronics Video Tool\nComplete each stage with guided fields, validate, then render. JSON contracts are generated automatically.")
    with gr.Row():
        bundle_in=gr.File(label="Import project bundle (.zip)",file_types=[".zip"]); import_btn=gr.Button("Import Bundle"); reset_btn=gr.Button("Load Benchmark Defaults")
    import_status=gr.Markdown(""); fields=[]
    with gr.Tab("1 · Project"):
        pid=gr.Textbox(d[0],label="Project ID"); topic=gr.Textbox(d[1],label="Topic"); objective=gr.Textbox(d[2],label="Learning objective",lines=3)
        with gr.Row():
            audience=gr.Dropdown(["beginner","intermediate","advanced"],d[3],label="Audience",allow_custom_value=True); platform=gr.Dropdown(["youtube_shorts","youtube","instagram_reels","tiktok"],d[4],label="Platform",allow_custom_value=True); aspect=gr.Dropdown(["9:16","16:9","1:1","4:5"],d[5],label="Aspect ratio",allow_custom_value=True)
            target_duration=gr.Number(d[6],label="Target seconds"); language=gr.Textbox(d[7],label="Language")
    fields += [pid,topic,objective,audience,platform,aspect,target_duration,language]
    with gr.Tab("2 · Technical truth"):
        facts=gr.Dataframe(headers=["fact_id","claim"],value=d[8],datatype=["str","str"],type="array",label="Verified facts",row_count=(1,"dynamic"),column_count=2); forbidden=gr.Textbox(d[9],label="Forbidden visuals (one per line)",lines=4)
        rules=gr.Dataframe(headers=["rule_id","severity","assertion"],value=d[10],datatype=["str","str","str"],type="array",label="QA rules",row_count=(1,"dynamic"),column_count=3); gr.Markdown("Severity: `blocker`, `major`, or `minor`.")
    fields += [facts,forbidden,rules]
    with gr.Tab("3 · Visual style"):
        visual=gr.Textbox(d[11],label="Visual language"); background=gr.Textbox(d[12],label="Background style / asset"); highlight=gr.Textbox(d[13],label="Highlight color"); motion=gr.CheckboxGroup(["fade","scale","arrow","waveform","state_change"],d[14],label="Motion grammar")
    fields += [visual,background,highlight,motion]
    with gr.Tab("4 · Storyboard"):
        story_total=gr.Number(d[15],label="Total duration (seconds)"); storyboard=gr.Dataframe(headers=["scene_id","start_seconds","end_seconds","duration_seconds","narration_draft"],value=d[16],datatype=["str","number","number","number","str"],type="array",label="Storyboard scenes",row_count=(1,"dynamic"),column_count=5,wrap=True)
    fields += [story_total,storyboard]
    with gr.Tab("5 · Scene specification"):
        gr.Markdown("**Main images:** `content_image_asset` is the foreground/source image rendered as the scene's main visual. `image_fit` accepts `contain` or `cover`; `image_motion` accepts `none` or `slow_zoom`. **Backgrounds:** `background_asset` is rendered behind the main image."); specs=gr.Dataframe(headers=SPEC_COLUMNS,value=d[17],datatype=["str","number","number","number","str","str","str","str","str"],type="array",label="Scene specifications",row_count=(1,"dynamic"),column_count=9)
    fields += [specs]
    with gr.Tab("6 · Assets"):
        gr.Markdown("## Main scene images (used to make the video)")
        scene_image_location=gr.Markdown(scene_image_location_status(d[0]))
        scene_image_uploads=gr.File(value=d[44],label="Upload main scene images in scene order",file_count="multiple",file_types=[".png",".jpg",".jpeg",".webp",".bmp"],type="filepath")
        with gr.Row():
            register_scene_images_btn=gr.Button("Store and assign uploaded images",variant="primary")
            scan_scene_images_btn=gr.Button("Scan the scene_images folder and assign")
        scene_image_status=gr.Markdown("")
        gr.Markdown("After assignment, verify the `content_image_asset` column in Stage 5. These images become the main visuals in the generated video.")
        gr.Markdown("---\n## Background assets (optional)")
        gr.Markdown("""### Where assets come from

Background asset IDs can now point to an uploaded image/video or a background created in this portal. Each scene uses the ID in its `background_asset` column.

- Built-in renderer source: `/app/engine/render_engine.py` inside Docker
- Uploaded files inside Docker: `/app/projects/<project_id>/input/assets/`
- Matching host folder: `projects/<project_id>/input/assets/`

Supported source types: `built_in_grid`, `solid_color`, `gradient`, `external_image`, and `external_video`.""")
        asset_location=gr.Markdown(asset_location_status(d[0]))
        asset_uploads=gr.File(value=d[43],label="Upload backgrounds (PNG, JPEG, WebP, BMP, MP4, MOV, MKV, WebM, AVI, M4V)",file_count="multiple",file_types=[".png",".jpg",".jpeg",".webp",".bmp",".mp4",".mov",".mkv",".webm",".avi",".m4v"],type="filepath")
        register_assets_btn=gr.Button("Register uploaded files as background asset IDs")
        asset_status=gr.Markdown("")
        assets=gr.Dataframe(headers=["asset_id","source_type","source_value"],value=d[18],datatype=["str","str","str"],type="array",label="Background asset registry",row_count=(1,"dynamic"),column_count=3)
        gr.Markdown("#### Create a background in the portal")
        with gr.Row():
            portal_bg_id=gr.Textbox("portal_background",label="New asset ID")
            portal_bg_type=gr.Dropdown(["built_in_grid","solid_color","gradient"],value="solid_color",label="Background type")
            portal_primary=gr.ColorPicker("#0F172A",label="Primary color")
            portal_secondary=gr.ColorPicker("#1E3A5F",label="Gradient secondary color")
        add_portal_bg_btn=gr.Button("Add/update portal background")
        gr.Markdown("#### Assign a background to scenes")
        with gr.Row():
            apply_asset_id=gr.Dropdown([row[0] for row in d[18]],value="bg_engineering_grid_v1",label="Registered asset ID",allow_custom_value=False)
            apply_asset_btn=gr.Button("Apply this background to every scene")
        apply_asset_status=gr.Markdown("")
    fields += [assets]
    with gr.Tab("7 · Narration timing"):
        gr.Markdown("List scene IDs in playback order; text and timing come from the storyboard."); narration=gr.Dataframe(headers=["scene_id"],value=d[19],datatype=["str"],type="array",label="Narration sequence",row_count=(1,"dynamic"),column_count=1)
    fields += [narration]
    with gr.Tab("8 · Render settings"):
        with gr.Row(): width=gr.Number(d[20],precision=0,label="Width"); height=gr.Number(d[21],precision=0,label="Height"); fps=gr.Number(d[22],precision=0,label="FPS"); render_duration=gr.Number(d[23],label="Duration")
        with gr.Row(): container=gr.Dropdown(["mp4","mov","webm"],d[24],label="Container",allow_custom_value=True); codec=gr.Dropdown(["h264","h265","vp9"],d[25],label="Codec",allow_custom_value=True); seed=gr.Number(d[30],precision=0,label="Random seed"); fixed=gr.Number(d[31],precision=0,label="Fixed frames")
        with gr.Row(): safe_top=gr.Number(d[26],precision=0,label="Safe top"); safe_bottom=gr.Number(d[27],precision=0,label="Safe bottom"); safe_left=gr.Number(d[28],precision=0,label="Safe left"); safe_right=gr.Number(d[29],precision=0,label="Safe right")
        filename=gr.Textbox(d[32],label="Output filename")
        gr.Markdown("### Audio and voice")
        audio_source=gr.Radio([("Generate narration from storyboard","generated_voice"),("Use one recorded/uploaded file as the main track","custom_audio"),("Record narration separately for each scene","per_scene_audio")],value=d[33],label="Main audio source")
        audio_file=gr.Audio(value=d[34],sources=["upload","microphone"],type="filepath",label="Single full-length main audio track")
        audio_timing=gr.Markdown(audio_timing_status(None,d[23]))
        scene_audio_state=gr.State(d[35])
        gr.Markdown("#### Scene-by-scene narration recorder\nSelect a scene, record only its narration, then click **Save recording to scene**. Each clip is padded or trimmed to that scene's exact duration.")
        default_scenes=storyboard_rows(d[16]); default_scene_ids=[row["scene_id"] for row in default_scenes]
        default_scene_choices=[(f"{row['scene_id']} · {row['start_seconds']:.2f}s–{row['end_seconds']:.2f}s · {row['duration_seconds']:.2f}s",row["scene_id"]) for row in default_scenes]
        with gr.Row():
            recording_scene=gr.Dropdown(default_scene_choices,value=default_scene_ids[0] if default_scene_ids else None,label="Scene being recorded (ID · start–end · target length)")
            scene_recording=gr.Audio(sources=["microphone","upload"],type="filepath",label="Recording for selected scene")
        selected_scene_timing=gr.Markdown(scene_timing_status(default_scene_ids[0] if default_scene_ids else None,d[16]))
        with gr.Row():
            save_scene_btn=gr.Button("Save recording to scene",variant="primary")
            clear_scene_btn=gr.Button("Clear selected scene recording")
        scene_record_status=gr.Markdown("No scene recording saved in this session yet.")
        scene_timeline=gr.Dataframe(headers=["scene_id","seek_start","seek_end","target_length","recorded_length","recording_status"],value=scene_timeline_rows(d[16],d[35]),datatype=["str","str","str","str","str","str"],interactive=False,label="Narration timeline and recording completion",column_count=6)
        scene_preview=gr.Audio(label="Combined scene-aligned narration preview (use seek positions shown above)",interactive=False)
        with gr.Row():
            voice_type=gr.Dropdown(["male","female","robotic","custom"],d[36],label="Generated voice type")
            custom_voice=gr.Textbox(d[37],label="Custom eSpeak voice/variant",placeholder="Examples: en-us, en-us+m3, en-us+f3, en-us+croak")
            audio_volume=gr.Slider(0.0,2.0,d[38],step=0.05,label="Main audio volume")
        gr.Markdown("Generated narration is not mixed in when recorded/uploaded audio is selected. Custom audio is padded or trimmed to the exact video duration.")
    fields += [width,height,fps,render_duration,container,codec,safe_top,safe_bottom,safe_left,safe_right,seed,fixed,filename,audio_source,audio_file,scene_audio_state,voice_type,custom_voice,audio_volume]
    with gr.Tab("9 · Verification baseline"):
        reference=gr.Textbox(d[39],label="Reference URL"); duration_error=gr.Number(d[40],label="Maximum duration error"); overall=gr.Dropdown(["NOT_RUN","PASS","FAIL"],d[41],label="Initial status",allow_custom_value=True); blockers=gr.Textbox(d[42],label="Known blocker violations",lines=4)
    fields += [reference,duration_error,overall,blockers,asset_uploads,scene_image_uploads]
    with gr.Row(): validate_btn=gr.Button("Validate Inputs"); start_btn=gr.Button("▶ START / RENDER",variant="primary"); export_btn=gr.Button("Export Assistant Bundle")
    status=gr.Markdown("Ready.")
    with gr.Tab("Output Video"): video_out=gr.Video(label="Rendered MP4")
    with gr.Tab("Verification Results"): verification_out=gr.Code(label="Verification report",language="json",lines=24)
    with gr.Tab("Render Manifest / Logs"): manifest_out=gr.Code(label="Render manifest / error",language="json",lines=24)
    bundle_out=gr.File(label="Portable project bundle")
    audio_file.change(audio_timing_status,inputs=[audio_file,render_duration],outputs=[audio_timing])
    render_duration.change(audio_timing_status,inputs=[audio_file,render_duration],outputs=[audio_timing])
    recording_scene.change(scene_timing_status,inputs=[recording_scene,storyboard],outputs=[selected_scene_timing])
    storyboard.change(sync_scene_controls,inputs=[storyboard,scene_audio_state],outputs=[recording_scene,scene_timeline,selected_scene_timing])
    save_scene_btn.click(save_scene_recording,inputs=[pid,recording_scene,scene_recording,storyboard,scene_audio_state],outputs=[scene_audio_state,scene_record_status,scene_timeline,scene_preview,scene_recording])
    clear_scene_btn.click(clear_scene_recording,inputs=[pid,recording_scene,storyboard,scene_audio_state],outputs=[scene_audio_state,scene_record_status,scene_timeline,scene_preview,scene_recording])
    scene_timeline.select(select_scene_from_timeline,inputs=[storyboard],outputs=[recording_scene,selected_scene_timing,scene_preview])
    register_assets_btn.click(register_background_uploads,inputs=[pid,asset_uploads,assets],outputs=[assets,asset_status])
    register_scene_images_btn.click(register_scene_images,inputs=[pid,scene_image_uploads,assets,specs],outputs=[assets,specs,scene_image_status,scene_image_uploads])
    scan_scene_images_btn.click(scan_scene_image_folder,inputs=[pid,assets,specs],outputs=[assets,specs,scene_image_status])
    add_portal_bg_btn.click(add_portal_background,inputs=[portal_bg_id,portal_bg_type,portal_primary,portal_secondary,assets],outputs=[assets,asset_status])
    apply_asset_btn.click(apply_background_to_scenes,inputs=[apply_asset_id,specs],outputs=[specs,apply_asset_status])
    assets.change(update_background_choices,inputs=[assets,apply_asset_id],outputs=[apply_asset_id])
    pid.change(asset_location_status,inputs=[pid],outputs=[asset_location])
    pid.change(scene_image_location_status,inputs=[pid],outputs=[scene_image_location])
    validate_btn.click(save_and_validate,inputs=fields,outputs=[status,verification_out]); start_btn.click(render_project,inputs=fields,outputs=[status,video_out,verification_out,manifest_out,bundle_out]); export_btn.click(export_only,inputs=fields,outputs=[bundle_out,status])
    import_event=import_btn.click(import_bundle,inputs=[bundle_in],outputs=fields+[import_status])
    import_event.then(refresh_scene_audio_ui,inputs=[pid,storyboard,scene_audio_state],outputs=[recording_scene,scene_timeline,selected_scene_timing,scene_preview,scene_record_status])
    reset_event=reset_btn.click(lambda:(*bundle_to_form(default_bundle()),"✅ Benchmark defaults restored."),outputs=fields+[import_status])
    reset_event.then(refresh_scene_audio_ui,inputs=[pid,storyboard,scene_audio_state],outputs=[recording_scene,scene_timeline,selected_scene_timing,scene_preview,scene_record_status])

if __name__=="__main__":
    demo.launch(server_name=os.environ.get("AEV_HOST","127.0.0.1"),server_port=int(os.environ.get("AEV_PORT","7860")),inbrowser=os.environ.get("AEV_INBROWSER","1").lower() not in {"0","false","no"},show_error=True)
